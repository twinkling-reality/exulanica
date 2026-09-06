/**
 * The point-map shader, in GLSL for WebGL2 and WGSL for WebGPU.
 *
 * WHY BOTH SOURCES EXIST, which is a finding rather than a style choice. PlayCanvas can transpile
 * a custom GLSL shader to WGSL at runtime, but only if the application supplies `glslangUrl` and
 * `twgslUrl` when creating the device. Those two WASM transpilers are NOT shipped inside the
 * `playcanvas` npm package (verified against 2.21.4: no glslang or twgsl artifact anywhere in the
 * tarball). So a custom shader on the WebGPU path means either two hand-written sources or two
 * extra network fetches of third-party WASM inside the measurement. This file takes the first
 * option, which is also the only one that keeps the bake-off numbers clean.
 *
 * A SECOND FINDING LIVES IN THE WGSL. WGSL has no point-size output. The GLSL path writes
 * `gl_PointSize` and gets perspective-correct point sprites; the WebGPU `point-list` topology
 * draws every point as exactly one pixel and there is no way to ask for more. PlayCanvas's own
 * engine acknowledges this by writing `gl_PointSize = 1.0` in its only reference to point size.
 * The consequence for Exulanica is direct: the WebGPU path cannot render a point map that looks
 * like a surface, only one that looks like static, unless the geometry is rebuilt as expanded
 * quads at six vertices per point. See the harness notes.
 *
 * Everything the shader branches on is REAL SEMANTIC STATE, uploaded from `semantics.ts`, which
 * derives it from `readsAsUnconfirmed` in atlas-core. There is no "look mysterious" constant.
 */

/**
 * Shared numeric contract between the two sources, so a change cannot land in one and not the
 * other. Kept as a comment block rather than string interpolation because a preprocessor
 * substitution inside shader text is exactly where these two would silently diverge.
 *
 *   aPosition   vec3   local frame, metres, +Y up, -Z forward
 *   aColor      vec4   rgb albedo, ALPHA IS SUPPORT OR CONFIDENCE, declared by the .opm header
 *   aTags       vec2   x semantic segment id, indexes uSegState; y flags word, bit 0 one-sided
 *
 *   uSegState[16] vec4  x unconfirmed, y provenance slot 0..3, z presence-marker-only, w conf floor
 *   uIsland       vec4  x emphasis scalar, y footprint radius local, z dissolve band start, w scale
 *   uPoint        vec4  x size gain, y max size px, z projection scale px, w time seconds
 *   uSupportFloor float floor on the alpha divisor that widens a thinly sampled sprite
 *   uFog          vec4  x start, y end, z density, w enabled
 *   uFogColor     vec3
 *   uPalette[4]   vec4  one per provenance class: capture, inference, user, external
 *   uLens         vec4  xyz proof-tier colour, w tint strength; all zero is the lens switched off
 *   uExposure     float display gain, never per point
 */

export const POINT_VERTEX_GLSL = /* glsl */ `
attribute vec3 aPosition;
attribute vec4 aColor;
/**
 * Two components since OPM/2, and the same two on both graphics paths.
 *
 * ADR-0010 D3 widened the container's segment attribute to a four-byte tags section of two
 * uint16 channels, because WebGPU rejects a vertex stream whose arrayStride is not a multiple of
 * 4. The binding used to widen it on the CPU for WebGPU only, so this attribute was one float
 * here and a vec2 there from the same bytes. It is now the same shape in both, and y is a
 * flags word that nothing reads yet: ADR-0010 D4 says outright that whether bit 0 removes the
 * silhouette fringing "is the thing to measure before writing it", and consuming it before that
 * measurement would be inventing an appearance for a number nobody has looked at.
 */
attribute vec2 aTags;

uniform mat4 matrix_model;
uniform mat4 matrix_viewProjection;
uniform vec3 view_position;

uniform vec4 uSegState[16];
uniform vec4 uIsland;
uniform vec4 uPoint;
/** Lower bound on the per-point support divisor. 1.0 disables spacing-aware sizing. */
uniform float uSupportFloor;
uniform vec4 uFog;

varying vec4 vColor;
varying vec4 vSemantic;
varying float vFogAmount;

// One hash, used for the particulate dissolve. Deterministic per point, so the boundary does not
// crawl when the camera moves; it is a property of the point, not of the frame.
float hash1(float n) {
    return fract(sin(n * 12.9898) * 43758.5453);
}

void main(void) {
    int seg = int(aTags.x + 0.5);
    vec4 state = uSegState[seg];

    float presenceOnly = state.z;
    float unconfirmed  = state.x;
    float confidence   = aColor.a * state.w;

    vec4 worldPos = matrix_model * vec4(aPosition, 1.0);
    float viewDist = length(worldPos.xyz - view_position);

    // The dissolving, foggy, particulate boundary. Islands have no edges: the outer fifth of the
    // footprint is a band where survival falls off. Computed in LOCAL radial distance because the
    // footprint is a local property; the band start comes from atlas-core.
    float radial = length(aPosition.xz);
    float band = uIsland.y > uIsland.z
        ? clamp((radial - uIsland.z) / (uIsland.y - uIsland.z), 0.0, 1.0)
        : 0.0;

    // Survival probability. Three independent reasons a point may not be drawn, and all three are
    // semantic rather than decorative: it is out past the dissolve band, the model was not
    // confident it was ever there, or the link that would confirm it is still a guess.
    float survive = 1.0 - band;
    survive *= mix(1.0, confidence, unconfirmed);
    survive *= mix(1.0, 0.35 + 0.65 * confidence, unconfirmed);
    survive *= uIsland.x > 0.0 ? 1.0 : 0.0;

    float r = hash1(float(gl_VertexID) * 0.6180339887);

    if (presenceOnly > 0.5 || r > survive) {
        // Culled. Pushed behind the near plane rather than discarded in the fragment stage, so a
        // culled point costs no rasterisation at all.
        gl_Position = vec4(0.0, 0.0, 2.0, 1.0);
        gl_PointSize = 0.0;
        vColor = vec4(0.0);
        vSemantic = vec4(0.0);
        vFogAmount = 0.0;
        return;
    }

    gl_Position = matrix_viewProjection * worldPos;

    // Perspective-correct sprite size, clamped so a near point cannot become a screen-filling
    // quad and a far one never falls below a pixel.
    //
    // A point stands for its OWN cell rather than an average one. uPoint.x is the world width
    // that suits a sample at the map's median spacing; the alpha channel says how much coarser
    // this particular sample is, so dividing by it widens the sprite exactly where the surface
    // was sampled thinly. Sky thirty metres out and pavement at a grazing angle stop being a
    // scatter of dots with holes between them and become the faint, coarse surface they are:
    // the fragment stage is already dimming them by the same number, so a widened splat reads as
    // less certain rather than as more geometry.
    //
    // uSupportFloor is 1.0 for a producer whose alpha is not a spacing ratio, which makes the
    // division exactly 1 and leaves that file rendering as it always did.
    float spread = uPoint.x / max(aColor.a, uSupportFloor);
    gl_PointSize = clamp(spread * uPoint.z / max(viewDist, 0.001), 1.0, uPoint.y);

    float fogAmount = 0.0;
    if (uFog.w > 0.5) {
        float t = clamp((viewDist - uFog.x) / max(uFog.y - uFog.x, 0.001), 0.0, 1.0);
        fogAmount = 1.0 - exp(-uFog.z * t * t * 4.0);
    }

    vColor = vec4(aColor.rgb, confidence);
    vSemantic = vec4(unconfirmed, state.y, band, uIsland.x);
    vFogAmount = fogAmount;
}
`;

export const POINT_FRAGMENT_GLSL = /* glsl */ `
precision highp float;

uniform vec4 uPalette[4];
uniform vec3 uFogColor;
uniform vec4 uPoint;
/**
 * The proof lens, as a RESOLVED colour and nothing else.
 *
 * xyz is the colour of the tier this island is currently showing, and w is how strongly to tint.
 * Which tier that is, and which colour a tier gets, are both decided in @exulanica/presentation
 * (proof-lens.ts) and delivered here already resolved: the shader cannot see a tier, cannot index
 * a palette, and therefore cannot disagree with the legend the status panel prints.
 *
 * All zero is the lens switched off, and off must be indistinguishable from a build that has no
 * lens. That is why this is a mix at the end rather than a branch: mix(rgb, anything, 0.0) is
 * exactly rgb, so the off state costs one instruction and changes no pixel.
 */
uniform vec4 uLens;
/**
 * Exposure. A point map carries albedo with no lighting model, so unlit albedo alone renders
 * dark. This is a single display gain and it is NOT a per-point value: it must never be able to
 * make one point look more certain than another.
 */
uniform float uExposure;

varying vec4 vColor;
varying vec4 vSemantic;
varying float vFogAmount;

void main(void) {
    // Soft round edges. A square point sprite reads as a pixel grid, which is the one thing the
    // dissolving boundary must not look like.
    vec2 d = gl_PointCoord * 2.0 - 1.0;
    float r2 = dot(d, d);
    if (r2 > 1.0) discard;
    float soft = smoothstep(1.0, 0.25, r2);

    int slot = int(vSemantic.y + 0.5);
    vec4 tint = uPalette[slot];

    vec3 rgb = mix(vColor.rgb, vColor.rgb * tint.rgb, tint.a);

    // Unconfirmed points breathe: a slow, low-amplitude luminance drift, phase-offset by the
    // provenance slot so inference and external do not pulse in lockstep.
    float breathe = 1.0 + vSemantic.x * 0.18 * sin(uPoint.w * 1.3 + vSemantic.y * 2.1);
    rgb *= breathe;

    rgb = mix(rgb, uFogColor, vFogAmount);

    // Emphasis: one float, exactly as the performance contract requires. It controls opacity and
    // saturation together, so a muted island reads as further away rather than merely darker.
    float emphasis = vSemantic.w;
    float luma = dot(rgb, vec3(0.2126, 0.7152, 0.0722));
    rgb = mix(vec3(luma), rgb, 0.35 + 0.65 * emphasis);

    // CONFIDENCE FADES TOWARD THE GROUND, IT DOES NOT ERASE AND IT DOES NOT DARKEN. The vertex
    // stage has already used confidence to thin the cloud stochastically, so applying it a
    // second time as coverage would delete an uncertain surface twice over and leave nothing.
    //
    // It fades toward the ground colour rather than toward black, because "faint" has to mean
    // faint in the theme the world is actually wearing. Multiplying the albedo down assumes a
    // dark sky: on the light origin landscape it drove low-confidence points AWAY from the
    // background and a barely sampled surface came out as the most prominent thing on screen,
    // which is the exact inverse of what this line is for. Mixing toward the ground reads as
    // receding under both themes, and that is the whole claim being made.
    rgb = mix(rgb, uFogColor, (1.0 - vColor.a) * 0.55);
    rgb *= uExposure;

    // THE PROOF LENS, APPLIED LAST: THE TIER'S HUE AT THIS PIXEL'S OWN BRIGHTNESS.
    //
    // The tier is a property of the whole island, so tinting flat would erase the surface and
    // leave a coloured silhouette: a visitor could then read the tier but not check it against
    // what is being drawn, which is the opposite of the point. Keeping the luminance and replacing
    // only the hue leaves the geometry legible underneath the answer about where it came from.
    //
    // The delivered colour is DIVIDED BY ITS OWN LUMINANCE before it is applied. Multiplying by it
    // instead was the first version, and on this palette it read as desaturation rather than as a
    // colour: the tier colours are dark by design, so colour times luma lands near the ground for
    // every bright pixel and the picture merely goes grey. Normalising keeps the hue the legend
    // names at the brightness the surface actually has. This rescales a colour; it does not choose
    // one, exactly as the provenance uPalette tint above it does not.
    float lensLuma = dot(rgb, vec3(0.2126, 0.7152, 0.0722));
    vec3 lensHue = uLens.rgb / max(dot(uLens.rgb, vec3(0.2126, 0.7152, 0.0722)), 0.004);
    rgb = mix(rgb, clamp(lensHue * lensLuma, 0.0, 1.0), uLens.a);

    // Coverage is the sprite footprint and the emphasis, and nothing else.
    float coverage = soft * (0.35 + 0.65 * emphasis) * (1.0 - vSemantic.z * 0.45);

    #ifdef POINT_BLEND
        gl_FragColor = vec4(rgb, coverage * (0.4 + 0.6 * vColor.a));
    #else
        // Opaque path: alpha test rather than blending. Depth-correct, order-independent, and it
        // is the reason a per-point global sort is not needed for a point map at all.
        if (coverage < 0.2) discard;
        gl_FragColor = vec4(rgb, 1.0);
    #endif
}
`;

/**
 * WGSL. Structurally identical, minus the one thing WGSL cannot express.
 *
 * PlayCanvas's WGSL convention: `attribute`, `varying` and `uniform` declarations are rewritten by
 * the engine's shader processor into the VertexInput / VertexOutput structs and the `uniform`
 * binding, and the entry points must be named `vertexMain` and `fragmentMain`.
 */
export const POINT_VERTEX_WGSL = /* wgsl */ `
attribute aPosition : vec3f;
attribute aColor : vec4f;
/**
 * NOTE THE TYPE. THE COMPONENT COUNT NO LONGER DIFFERS FROM THE GLSL PATH; THE SPELLING DOES.
 *
 * WebGPU requires every vertex stream's arrayStride to be a multiple of 4. Under OPM/1 the
 * container stored one uint16 per point and this binding widened it on the CPU for WebGPU only,
 * so the attribute was two components here and one on WebGL2 from the same bytes. ADR-0010 D3
 * put the four-byte tags section in the container instead, so both paths now read the same two
 * channels and the per-point pass is gone.
 *
 * PlayCanvas rewrites the input struct field to the integer form and emits a private variable of
 * the DECLARED type plus a cast:
 *
 *     @location(8) aTags: vec2u,      // in the generated VertexInput struct
 *     var<private> aTags : vec2f;     // what this source actually reads
 *     aTags = vec2f(input.aTags);     // inserted by _pcCopyInputs
 *
 * So the body must read the BARE NAME, never input.aTags, which has the other type. Declaring
 * a type the engine's float-to-int map does not cover emits aTags: null into the struct and
 * fails to parse, and that failure is SILENT in the release engine build: the pipeline is
 * rejected, the draw is dropped, the canvas stays empty and the frame rate goes up. The harness
 * has a render-validity guard because of exactly this.
 */
attribute aTags : vec2f;

uniform matrix_model : mat4x4f;
uniform matrix_viewProjection : mat4x4f;
uniform view_position : vec3f;

uniform uSegState : array<vec4f, 16>;
uniform uIsland : vec4f;
uniform uPoint : vec4f;
uniform uFog : vec4f;

varying vColor : vec4f;
varying vSemantic : vec4f;
varying vFogAmount : f32;

fn hash1(n : f32) -> f32 {
    return fract(sin(n * 12.9898) * 43758.5453);
}

@vertex
fn vertexMain(input : VertexInput) -> VertexOutput {
    var output : VertexOutput;

    let seg : i32 = i32(aTags.x);
    let state : vec4f = uniform.uSegState[seg];

    let presenceOnly : f32 = state.z;
    let unconfirmed : f32 = state.x;
    let confidence : f32 = aColor.a * state.w;

    let worldPos : vec4f = uniform.matrix_model * vec4f(aPosition, 1.0);
    let viewDist : f32 = length(worldPos.xyz - uniform.view_position);

    let radial : f32 = length(aPosition.xz);
    var band : f32 = 0.0;
    if (uniform.uIsland.y > uniform.uIsland.z) {
        band = clamp((radial - uniform.uIsland.z) / (uniform.uIsland.y - uniform.uIsland.z), 0.0, 1.0);
    }

    var survive : f32 = 1.0 - band;
    survive = survive * mix(1.0, confidence, unconfirmed);
    survive = survive * mix(1.0, 0.35 + 0.65 * confidence, unconfirmed);
    if (uniform.uIsland.x <= 0.0) {
        survive = 0.0;
    }

    let r : f32 = hash1(f32(pcVertexIndex) * 0.6180339887);

    if (presenceOnly > 0.5 || r > survive) {
        output.position = vec4f(0.0, 0.0, 2.0, 1.0);
        output.vColor = vec4f(0.0);
        output.vSemantic = vec4f(0.0);
        output.vFogAmount = 0.0;
        return output;
    }

    output.position = uniform.matrix_viewProjection * worldPos;

    // NOTE: there is deliberately no point-size write here. WGSL has no equivalent of
    // gl_PointSize, and the WebGPU point-list topology rasterises one pixel per point. This is
    // not an omission to be fixed; it is the limitation the bake-off is reporting.

    var fogAmount : f32 = 0.0;
    if (uniform.uFog.w > 0.5) {
        let t : f32 = clamp((viewDist - uniform.uFog.x) / max(uniform.uFog.y - uniform.uFog.x, 0.001), 0.0, 1.0);
        fogAmount = 1.0 - exp(-uniform.uFog.z * t * t * 4.0);
    }

    output.vColor = vec4f(aColor.rgb, confidence);
    output.vSemantic = vec4f(unconfirmed, state.y, band, uniform.uIsland.x);
    output.vFogAmount = fogAmount;
    return output;
}
`;

export const POINT_FRAGMENT_WGSL = /* wgsl */ `
uniform uPalette : array<vec4f, 4>;
uniform uFogColor : vec3f;
uniform uPoint : vec4f;
/** The proof lens: a resolved tier colour in xyz and its tint strength in w. See the GLSL source. */
uniform uLens : vec4f;
uniform uExposure : f32;

varying vColor : vec4f;
varying vSemantic : vec4f;
varying vFogAmount : f32;

@fragment
fn fragmentMain(input : FragmentInput) -> FragmentOutput {
    var output : FragmentOutput;

    // One pixel per point on this path, so there is no point-sprite coverage to soften.
    let slot : i32 = i32(input.vSemantic.y + 0.5);
    let tint : vec4f = uniform.uPalette[slot];

    var rgb : vec3f = mix(input.vColor.rgb, input.vColor.rgb * tint.rgb, tint.a);

    let breathe : f32 = 1.0 + input.vSemantic.x * 0.18 * sin(uniform.uPoint.w * 1.3 + input.vSemantic.y * 2.1);
    rgb = rgb * breathe;

    rgb = mix(rgb, uniform.uFogColor, input.vFogAmount);

    let emphasis : f32 = input.vSemantic.w;
    let luma : f32 = dot(rgb, vec3f(0.2126, 0.7152, 0.0722));
    rgb = mix(vec3f(luma), rgb, 0.35 + 0.65 * emphasis);

    // Confidence dims rather than erases, exactly as in the GLSL path. The vertex stage already
    // thinned the cloud by confidence; charging it again would delete uncertain surfaces twice.
    // Fades toward the ground rather than toward black. See the GLSL source for why.
    rgb = mix(rgb, uniform.uFogColor, (1.0 - input.vColor.a) * 0.55) * uniform.uExposure;

    // The proof lens: the tier's hue at this pixel's own brightness, exactly as in the GLSL path.
    let lensLuma : f32 = dot(rgb, vec3f(0.2126, 0.7152, 0.0722));
    let lensHue : vec3f = uniform.uLens.rgb / max(dot(uniform.uLens.rgb, vec3f(0.2126, 0.7152, 0.0722)), 0.004);
    rgb = mix(rgb, clamp(lensHue * lensLuma, vec3f(0.0), vec3f(1.0)), uniform.uLens.a);

    let coverage : f32 = (0.35 + 0.65 * emphasis) * (1.0 - input.vSemantic.z * 0.45);
    if (coverage < 0.2) {
        discard;
    }

    output.color = vec4f(rgb, 1.0);
    return output;
}
`;
