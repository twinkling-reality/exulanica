/** Adapted from the user-supplied Agent Orb reference. Colors are material literals;
 * the host's reading palette does not enter the shader. One triangle serves all three discs.
 */
export const ORB_VERTEX = `attribute vec2 position;
void main() { gl_Position = vec4(position, 0.0, 1.0); }`;

export const ORB_FRAGMENT = `precision highp float;
uniform vec2 uResolution;
uniform vec2 uOrigin;
uniform float uTime;
uniform float uAmplitude;
uniform float uPalette;
uniform float uMaterial;

float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123); }
float noise(vec2 p) {
  vec2 i = floor(p), f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash(i), hash(i + vec2(1, 0)), u.x),
             mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), u.x), u.y);
}
float fbm(vec2 p) {
  float v = 0.0, a = 0.5;
  for (int i = 0; i < 3; i++) { v += a * noise(p); p *= 2.0; a *= 0.5; }
  return v;
}
void main() {
  vec2 pixel = gl_FragCoord.xy - uOrigin;
  vec2 uv = (pixel * 2.0 - uResolution) / min(uResolution.x, uResolution.y);
  float d = length(uv);
  float edge = 2.0 / min(uResolution.x, uResolution.y);
  float mask = 1.0 - smoothstep(1.0 - edge, 1.0, d);
  if (mask <= 0.0) discard;
  // This mask is independent of time, emphasis, palette and material.
  vec3 deep = vec3(.39, .57, .68);
  vec3 mid = vec3(.61, .76, .81);
  vec3 pale = vec3(.84, .93, .96);
  if (uPalette > .5 && uPalette < 1.5) {
    deep = vec3(.44, .62, .56); mid = vec3(.64, .78, .68); pale = vec3(.89, .94, .81);
  } else if (uPalette > 1.5) {
    deep = vec3(.63, .46, .59); mid = vec3(.78, .65, .75); pale = vec3(.95, .85, .91);
  }
  float t = uTime;
  vec2 p = uv * (uMaterial < .5 ? vec2(1.0) : vec2(1.9, .62));
  float dn = min(d, 1.0);
  float centre = 1.0 - smoothstep(0.0, .92, dn);
  float beat = uAmplitude * (.30 + .70 * centre) * sin(dn * 10.0 - t * 5.5);
  p += uv / max(dn, .0001) * beat * .30;
  vec2 q = vec2(fbm(p + t * .10), fbm(p + vec2(5.2, 1.3) + t * .12));
  vec2 r = vec2(fbm(p + 1.9 * q + vec2(1.7, 9.2) + t * .09),
                fbm(p + 1.9 * q + vec2(8.3, 2.8) + t * .08));
  float f = fbm(p + 2.2 * r);
  float flare = uAmplitude * centre;
  if (uMaterial > .5) {
    float ink = clamp(smoothstep(.29, .55, f) + flare * .62, 0.0, 1.0);
    const float ang = .33;
    mat2 screen = mat2(cos(ang), -sin(ang), sin(ang), cos(ang));
    vec2 cell = fract((screen * pixel) / 6.5) - .5;
    float radius = sqrt(ink) * .564;
    float dots = 1.0 - smoothstep(radius - .10, radius + .10, length(cell));
    gl_FragColor = vec4(deep, dots * mask);
    return;
  }
  vec3 color = mix(deep, mid, smoothstep(.22, .58, f));
  color = mix(color, pale, smoothstep(.50, .86, f));
  float bands = sin((f + .32 * r.y) * 6.2831 * 1.7);
  float ribbon = mix(pow(abs(bands), 26.0), pow(abs(bands), 14.0), flare * .75);
  color = mix(color, vec3(1.0), clamp(ribbon * (.92 + flare * .8), 0.0, 1.0));
  color += uAmplitude * centre * centre * .26;
  float lum = dot(color, vec3(.299, .587, .114));
  color = clamp(mix(vec3(lum), color, 1.07), 0.0, 1.0);
  float z = sqrt(max(0.0, 1.0 - d * d));
  float lambert = clamp(dot(vec3(uv, z), normalize(vec3(-.35, .45, .82))), 0.0, 1.0);
  color *= .93 + .12 * lambert;
  color += pow(lambert, 14.0) * (.10 + uAmplitude * .30) * (.6 + .4 * f);
  color *= 1.0 - .14 * smoothstep(.72, 1.0, d);
  color += (hash(pixel) - .5) * .035;
  gl_FragColor = vec4(color, mask);
}`;
