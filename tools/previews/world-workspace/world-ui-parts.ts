// The parts page (world-ui-parts.html): every shared in-world part once, in its states, with the
// example words of DESIGN's frames, so a reviewer sees the parts beside the frames before any
// screen uses them. Nothing here reads a world. ?view=create, creating, refused, no-model and made
// show making a world's light parts (world-ui-create.ts) with stand-in answers; ?empty leaves the
// field empty, ?chosen=<n> marks a card chosen and ?thumbs=<folder> draws the cards' pictures.
// ?view=creature-describe, creature-making and creature-made show making a creature where it will
// stand (world-ui-creature.ts) with the sheet's example words, over ?picture= as the world.
import {
  areaBanner, cardWords, chip, glyphRows, keyWord, label, mountUiScale, notes, orb, page, pill, promptColumn, promptRow,
  nameTag, outline, path, ring, rule, scaleOf, shade, sideCard, stepList, tip,
} from './world-ui.ts';
import {
  createKeyRow, createOrb, filmStrip, lightLabel, lightLine, lightPage, lightSteps, madeNote, quietCommand, sentenceField, sentenceRow,
} from './world-ui-create.ts';
import { CREATE_WORDS, madeSpent, priceLine, refusalSpent, refusalWords, setValue, spendLine, startsLeftLine } from './create-words.mjs';
import { draftSteps, madeColumns, startCards } from './create-steps.mjs';
import { creatureField, madeGroup, makerLine, makingGroup, standLabel } from './world-ui-creature.ts';
// The product's fonts and their tokens, as the app loads them (bootstrap.ts).
import '../../../web/packages/presentation/src/tokens.css';

const root = document.body;
mountUiScale(root);
const query = new URLSearchParams(location.search);
const picture = query.get('picture');
if (picture) (root.querySelector('.parts-world') as HTMLElement).style.backgroundImage = `url(${JSON.stringify(picture)})`;
const add = <T extends Element>(part: T, host: Element = root): T => { host.append(part); return part; };
const div = (className: string): HTMLDivElement => { const made = document.createElement('div'); made.className = className; return made; };
const press = (): void => {};

const view = query.get('view');
if (view === 'creature-describe' || view === 'creature-making' || view === 'creature-made') {
  // Making a creature where it will stand (r17t, r19t, r19b), with stand-in answers: the round wader of the final pictures.
  const words = 'a round yellow body with a pale flat bill on two short legs', price = '0.37355520';
  const layer = add(div('wu-creature-layer'));
  if (view === 'creature-describe') {
    add(creatureField({ maximum: 400, onMake: press }).root, layer);
    const made = layer.querySelector('textarea')!; made.value = query.has('empty') ? '' : words;
    const under = layer.querySelector('.wu-creature-line')!; under.textContent = makerLine(price, 18);
    const count = layer.querySelector('.wu-creature-count')!; count.textContent = `${made.value.length} of 400`;
    const over = add(standLabel(), layer); over.style.left = 'calc(960 * var(--u))'; over.style.top = 'calc(640 * var(--u))';
  } else if (view === 'creature-making') {
    const making = makingGroup({ words, priceUsdAtMost: price });
    making.step('Making the creature 0:14');
    add(making.root, layer);
  } else {
    add(madeGroup({ label: 'yellow pond wader', words, modelName: 'Nemotron 3 Super 120B', spentUsd: '0.00420000', sketch: query.has('sketch'), placeable: true }), layer);
  }
} else if (view === 'create' || view === 'creating' || view === 'no-model' || view === 'refused') {
  // Making a world's light parts (frames 20 and 21) with the frames' example words and stand-in
  // answers; ?picture= is the chosen world's still picture behind them.
  (root.querySelector('.parts-world') as HTMLElement).hidden = true;
  const light = lightPage({ form: view === 'creating' ? 'creating' : 'create', picture, labelledBy: 'parts-create-title' });
  add(light.root);
  light.quiet.append(quietCommand({ onPress: press }));
  const words = 'Glass terraces with glowing pools above the sea at night, and a grand hotel at the top';
  if (view === 'creating') {
    light.head.append(lightLabel(CREATE_WORDS.creating));
    const quote = add(document.createElement('p'), light.head); quote.className = 'wu-light-quote'; quote.id = 'parts-create-title'; quote.textContent = `\u201c${words}\u201d`;
    const reads = [{ state: 'choosing', elapsed_seconds: 0 }, { state: 'drafting', elapsed_seconds: 1 }, { state: 'making', elapsed_seconds: 6 }, { state: 'making', elapsed_seconds: 12 }];
    light.lower.append(lightSteps(draftSteps(reads)).root, lightLine(spendLine({ spentUsd: 0.12, unknownUsd: 0.03 }, '1.4227'), { live: true }), lightLine(CREATE_WORDS.leave));
  } else {
    const title = add(document.createElement('h1'), light.head); title.className = 'wu-light-title'; title.id = 'parts-create-title'; title.tabIndex = -1; title.textContent = CREATE_WORDS.title;
    if (view === 'no-model') {
      const sentence = add(document.createElement('p'), light.head); sentence.className = 'wu-light-sentence'; sentence.textContent = CREATE_WORDS.noModel;
    } else {
      const field = sentenceField({ limit: 1000, value: query.get('empty') === null ? words : '' });
      const ready = field.field.value.trim().length > 0;
      light.head.append(sentenceRow(field, createOrb({ onPress: press, ready })));
      if (view === 'refused') {
        light.head.append(lightLine(refusalWords('world_not_a_place'), { tone: 'refused', live: true }), lightLine(refusalSpent({ spentUsd: 0.02 })!, { tone: 'refused' }));
      } else {
        light.head.append(lightLine(priceLine('1.4227')), lightLine(startsLeftLine(2)!));
      }
      createKeyRow(light.keys, { create: ready, start: false });
    }
    // Stand-in cards: the frames' names (the server's, never a list in code), one without a picture.
    // ?thumbs=<folder address> draws their pictures; without it each is the quiet tile.
    const thumbs = query.get('thumbs');
    const thumb = (name: string): string | null => (thumbs ? `${thumbs}${name}.jpg` : null);
    const cards = startCards([
      { key: 'town', name: 'Small town', picture: thumb('town') }, { key: 'bay', name: 'Terraces on the bay', picture: thumb('bay') },
      { key: 'canyon', name: 'Tower canyon', picture: thumb('canyon') },
    ], [{ key: 'wall', name: 'Wall city', picture: null, priceUsd: '0.4' }]);
    const strip = filmStrip(cards, press);
    light.lower.append(strip.root);
    if (query.get('chosen') !== null) strip.choose(Number(query.get('chosen')));
    else strip.cards.forEach((card) => card.removeAttribute('aria-current'));
  }
} else if (view === 'made') {
  // Frame 22's made note over the world, with the banner's made form.
  add(areaBanner({ name: 'Glass terraces', over: CREATE_WORDS.madeFromYourWords }).root).style.opacity = '1';
  const land = { title: 'on a coast, with a beach below and a terraced hill behind', chosen_by: 'words', words: ['by the sea'], fell_back: false };
  add(madeNote(madeColumns({ inIt: 'Four pools, a hotel, two pavilions, 40 people', set: setValue(land), notInItYet: 'A lighthouse', spent: madeSpent({ spentUsd: 0.31 }, '1.4227') })).root);
} else if (view === 'page') {
  const shown = page({ form: 'character' });
  shown.open(root);
  const column = add(div('parts-column'), shown.content);
  column.style.cssText = 'position:absolute;left:calc(900 * var(--u));top:calc(96 * var(--u));width:calc(880 * var(--u))';
  const title = add(document.createElement('h1'), column); title.className = 'wu-page-title'; title.textContent = 'Teo';
  const sub = add(document.createElement('p'), column); sub.className = 'wu-page-sub'; sub.textContent = 'Resident · Terraces on the bay';
  const sections = add(div('parts-sections'), column);
  sections.style.cssText = 'display:grid;grid-template-columns:calc(440 * var(--u)) calc(420 * var(--u));gap:calc(80 * var(--u));margin-top:calc(108 * var(--u))';
  const left = add(div(''), sections), right = add(div(''), sections);
  left.append(label('Model'), chip('Nemotron 3 Nano 30B', { page: true }));
  const price = add(document.createElement('p'), left); price.className = 'wu-small-text'; price.textContent = '$0.06 in · $0.24 out per million tokens';
  left.append(label('Run'));
  const run = add(div('wu-row'), left); run.style.gap = 'calc(20 * var(--u))';
  run.append(orb({ word: 'Run', onPress: press }));
  const big = add(document.createElement('p'), run); big.className = 'wu-big'; big.textContent = '10 minutes · at most $0.05';
  const field = add(document.createElement('textarea'), left); field.className = 'wu-field'; field.rows = 2; field.value = 'Quiet, kind, waits for friends by the bench.';
  const count = add(div('wu-count'), left); count.textContent = '43 of 300';
  right.append(label('What Teo did'));
  for (const [time, what, who, chosen] of [['07:09', 'Waited by the bench', 'Nemotron 3 Nano 30B · 7 choices', true], ['06:52', 'Said hello to Ines', 'Nemotron 3 Nano 30B · 9 choices', false], ['06:40', 'Walked to the lower pools', 'Routine', false]] as const) {
    const row = add(div('wu-list-row'), right);
    if (chosen) row.setAttribute('aria-current', 'true');
    const at = add(div('wu-time'), row); at.textContent = time;
    const words = add(div(''), row);
    const doing = add(div('wu-what'), words); doing.textContent = what;
    const by = add(div('wu-who'), words); by.textContent = who;
    if (chosen) words.append(keyWord({ keys: ['Enter'], word: 'Inspect decision', shortcut: 'Enter', onPress: press, small: true }));
  }
  right.append(label('Making'), stepList([
    { words: 'Your words and the picture\'s description', state: 'done', time: '0:02' },
    { words: 'Making its body and look', state: 'now', sub: 'An AI model, at most $0.01', time: '0:11' },
    { words: 'Checked, then kept', state: 'next' },
  ]));
  shown.keys.append(
    keyWord({ keys: ['M'], word: 'Model', shortcut: 'M', onPress: press }),
    keyWord({ keys: ['N'], word: 'Personality', shortcut: 'N', onPress: press }),
    keyWord({ keys: ['R'], word: 'Run', shortcut: 'R', onPress: press }),
    keyWord({ keys: ['Esc'], word: 'Back', shortcut: 'Escape', onPress: press }),
  );
} else if (query.get('view') === 'build') {
  for (const corner of ['tl', 'bl', 'tc']) add(div(`wu-scrim wu-${corner}`));
  add(div('wu-back')).append(keyWord({ keys: ['Esc'], word: 'Back', shortcut: 'Escape', onPress: press }));
  const mode = add(div('wu-mode'));
  const word = add(div('wu-mode-word'), mode); word.append(div('wu-marker'), 'Building');
  mode.append(keyWord({ keys: ['B'], word: 'Done', shortcut: 'B', onPress: press }));
  add(promptColumn([
    keyWord({ keys: 'mouse-click', word: 'Select' }),
    keyWord({ keys: ['Tab'], word: 'Next', shortcut: 'Tab', onPress: press }),
    keyWord({ keys: ['⌘Z'], word: 'Undo', shortcut: 'Meta+Z', onPress: press }),
  ])).classList.add('wu-hints');
  // The chosen part's outline; a copy where it would go, refused here, with the dotted path from its
  // spot (outlined dashed); and the name of a thing under the pointer.
  const footprint = outline(), copy = outline({ form: 'refused' }), origin = outline({ form: 'origin' }), way = path();
  add(footprint.root); add(copy.root); add(origin.root); add(way.root);
  const pointed = nameTag({ scale: () => scaleOf(root) });
  add(pointed.root);
  pointed.set({ name: 'Fan palm' });
  const card = sideCard({ build: true, scale: () => scaleOf(root) });
  add(card.root);
  card.body.append(cardWords({ title: 'Bench', lines: ['Made with this world · Lower pools'] }), promptColumn([
    keyWord({ keys: 'mouse-click', word: 'Drag to move' }),
    keyWord({ keys: ['[', ']'], word: 'Turn', shortcut: 'BracketLeft BracketRight', onPress: press }),
    keyWord({ keys: ['Del'], word: 'Remove', shortcut: 'Delete', onPress: press }),
  ]));
  const placeAll = (): void => {
    const x = innerWidth / 1920, y = innerHeight / 1080;
    footprint.place([{ x: 780 * x, y: 700 * y }, { x: 1010 * x, y: 680 * y }, { x: 1080 * x, y: 760 * y }, { x: 820 * x, y: 790 * y }]);
    origin.place([{ x: 300 * x, y: 820 * y }, { x: 470 * x, y: 805 * y }, { x: 520 * x, y: 870 * y }, { x: 330 * x, y: 890 * y }]);
    copy.place([{ x: 420 * x, y: 640 * y }, { x: 570 * x, y: 628 * y }, { x: 615 * x, y: 680 * y }, { x: 450 * x, y: 695 * y }]);
    way.place({ x: 410 * x, y: 850 * y }, { x: 515 * x, y: 662 * y });
    pointed.place(1460 * x, 470 * y);
    card.place({ left: 780 * x, top: 560 * y, right: 1080 * x, bottom: 790 * y, headY: 600 * y, waistY: 720 * y });
  };
  placeAll();
  addEventListener('resize', () => requestAnimationFrame(placeAll));
  notes(root, { place: 'build' }).show('Removed the fan palm.', { prompt: keyWord({ keys: ['⌘Z'], word: 'Undo', shortcut: 'Meta+Z', onPress: press, small: true }), ms: 0 });
} else if (query.get('view') === 'craft') {
  // The redraws' shared craft, each part once where its frame puts it (r02, r05, r24, r13), for
  // DESIGN's measure at 1920 and 1440.
  const at = (part: HTMLElement, css: string): HTMLElement => { part.style.cssText += css; return add(part); };
  const divider = document.createElement('i');
  divider.style.cssText = 'width:1px;height:calc(16 * var(--u));background:var(--pill-divider)';
  const people = document.createElement('span');
  people.style.cssText = 'font-size:var(--pill-text-small);color:var(--ink-2)';
  people.textContent = '24 people live here';
  at(pill('Terraces on the bay', divider, people), 'position:absolute;left:50%;top:var(--edge-inset);transform:translateX(-50%)');
  at(pill('06:55 · Day 1'), 'position:absolute;right:var(--edge-inset);top:var(--edge-inset)');
  at(tip('History', 'H'), 'position:absolute;left:calc(var(--edge-inset) + 56 * var(--u));top:calc(var(--edge-inset) + 4 * var(--u))');
  at(pill('W A S D to walk, drag to look, click someone to choose them'), 'position:absolute;left:50%;bottom:var(--edge-inset);transform:translateX(-50%);font-size:max(13px, calc(14 * var(--u)))');
  // Speech over a person, and a name further off.
  const said = at(shade(), 'left:calc(700 * var(--u));top:calc(300 * var(--u));text-align:center;white-space:nowrap;--shade-pad:calc(14 * var(--u));--shade-feather:calc(9 * var(--u));--shade-radius:calc(16 * var(--u))');
  said.innerHTML = '<div style="font:500 calc(14 * var(--u))/calc(20 * var(--u)) var(--font-sans)">Ines, to Teo</div><div style="margin-top:var(--space-8);font:italic 450 calc(20 * var(--u))/calc(24 * var(--u)) var(--font-sans)">\u201cThe boats are out early.\u201d</div>';
  at(shade({ small: true }), 'left:calc(420 * var(--u));top:calc(420 * var(--u));font:450 calc(14 * var(--u))/calc(20 * var(--u)) var(--font-sans)').textContent = 'Marco';
  // A character's choices (r05), building's held keys (r13), talking's bars (r24).
  const character = at(shade(), 'left:calc(1096 * var(--u));top:calc(296 * var(--u));--shade-pad:calc(24 * var(--u))');
  character.append(glyphRows([
    { key: 'Enter', word: "Teo's day", onPress: press }, { key: 'R', word: "Let Teo's model decide", onPress: press }, { key: 'V', word: 'Follow Teo', onPress: press },
  ], { glyph: 32, rowGap: 16, colGap: 16, word: 19, nudge: 0 }));
  // Building's held keys (W10) end their longest word 152 in from the right edge; talking's bars (T9) end 124 in.
  const held = at(shade(), 'right:calc(152 * var(--u));top:calc(312 * var(--u));--shade-pad:calc(24 * var(--u))');
  held.append(glyphRows([
    { key: 'mouse', word: 'Place' }, { key: '[ ]', word: 'Turn' }, { key: 'Del', word: 'Remove' }, { key: 'Esc', word: 'Put back' },
  ], { glyph: 'max(40px, calc(48 * var(--u)))', rowGap: 'max(12px, calc(16 * var(--u)))', colGap: 'max(16px, calc(20 * var(--u)))', word: 'max(28px, calc(32 * var(--u)))', nudge: -1 }));
  at(glyphRows([
    { key: 'V', word: 'Stop following', onPress: press }, { key: 'Enter', word: "Ines's day", onPress: press },
  ], { glyph: 32, rowGap: 16, colGap: 16, word: 18, nudge: 1, bars: true }), 'position:absolute;right:calc(124 * var(--u));bottom:calc(128 * var(--u))');
} else {
  for (const corner of ['tl', 'tr', 'bl', 'tc']) add(div(`wu-scrim wu-${corner}`));
  add(div('wu-back')).append(keyWord({ keys: ['Esc'], word: 'Your worlds', shortcut: 'Escape', onPress: press }));
  const clock = add(div('wu-clock'));
  const time = add(div('wu-clock-time'), clock);
  const hhmm = add(div('wu-clock-hhmm'), time); hhmm.textContent = '06:00';
  const state = add(div('wu-clock-state'), time); state.append(div('wu-glyph-pause'), 'Day 1 · Paused');
  clock.append(div('wu-divider'), keyWord({ keys: ['P'], word: 'Play', shortcut: 'P', onPress: press }));
  const mode = add(div('wu-mode'));
  const word = add(div('wu-mode-word'), mode); word.append(div('wu-marker'), 'Flying');
  mode.append(keyWord({ keys: ['F'], word: 'Land', shortcut: 'F', onPress: press }));
  const reticle = add(div('wu-reticle')); reticle.dataset.state = 'ready';
  for (let corner = 0; corner < 4; corner++) reticle.append(document.createElement('i'));
  const hints = add(promptRow([
    keyWord({ keys: ['W', 'A', 'S', 'D'], word: 'Move' }),
    keyWord({ keys: ['Shift'], word: 'Sprint' }),
    keyWord({ keys: 'mouse-click', word: 'Look' }),
    keyWord({ keys: ['F'], word: 'Fly', shortcut: 'F', onPress: press }),
    keyWord({ keys: ['E'], word: 'Inspect', shortcut: 'E', onPress: press }),
    keyWord({ keys: ['B'], word: 'Build', shortcut: 'B', onPress: press }),
    keyWord({ keys: ['H'], word: 'History', shortcut: 'H', onPress: press, disabled: true }),
  ], [2]));
  hints.classList.add('wu-hints');
  const banner = areaBanner({ name: 'Terraces on the bay', sub: '24 people live here' });
  add(banner.root).style.opacity = '1';
  // A chosen subject: its ring, and the card beside it, placed again when the window changes.
  const chosen = ring();
  add(chosen.root);
  const looking = nameTag({ scale: () => scaleOf(root) });
  add(looking.root);
  looking.set({ name: 'Ines', doing: 'Walking to the lower pools', model: 'Qwen3 235B Instruct', live: true });
  const beside = sideCard({ scale: () => scaleOf(root) });
  add(beside.root);
  beside.body.append(cardWords({ title: 'Teo', lines: ['Waiting by the bench', 'Teo\'s model chose this at 07:09, from 7 choices.'] }));
  beside.body.append(chip('Nemotron 3 Nano 30B', { live: true }), rule(), promptColumn([
    keyWord({ keys: ['Enter'], word: 'Details', shortcut: 'Enter', onPress: press }),
    keyWord({ keys: ['R'], word: 'Run', shortcut: 'R', onPress: press }),
    keyWord({ keys: ['V'], word: 'Follow', shortcut: 'V', onPress: press }),
  ]));
  // The chips' kinds, and a question card with its orb.
  const chips = add(div('wu-row'));
  chips.style.cssText = 'position:absolute;right:calc(40 * var(--u));top:calc(150 * var(--u));gap:calc(12 * var(--u))';
  chips.append(chip('Qwen3 235B Instruct'), chip('Private', { quiet: true }));
  const question = sideCard({ question: true, scale: () => scaleOf(root) });
  add(question.root);
  question.body.append(cardWords({ label: 'Teo', title: 'Run for 10 minutes', lines: ['Teo\'s model decides. Everyone else keeps their routine.'] }));
  const decide = add(div('wu-row'), question.body); decide.style.cssText = 'gap:calc(20 * var(--u));margin-top:calc(18 * var(--u))';
  decide.append(orb({ word: 'Run', onPress: press }));
  const most = add(div(''), decide); most.className = 'wu-small-text'; most.textContent = 'At most $0.05';
  question.body.append(rule(), promptRow([
    keyWord({ keys: ['Enter'], word: 'Run', shortcut: 'Enter', onPress: press }),
    keyWord({ keys: ['Esc'], word: 'Back', shortcut: 'Escape', onPress: press }),
  ]));
  // Reference positions on the 1920 by 1080 frame, in the window's own pixels.
  const placeAll = (): void => {
    const x = innerWidth / 1920, y = innerHeight / 1080, s = scaleOf(root);
    chosen.place(560 * x, 760 * y, 104 * s, 25 * s);
    looking.place(300 * x, 600 * y);
    beside.place({ left: 520 * x, top: 470 * y, right: 600 * x, bottom: 760 * y, headY: 480 * y, waistY: 640 * y });
    question.place({ left: 1240 * x, top: 330 * y, right: 1300 * x, bottom: 620 * y, headY: 340 * y, waistY: 480 * y });
  };
  placeAll();
  addEventListener('resize', () => requestAnimationFrame(placeAll));
  notes(root).show('Removed the fan palm.', { prompt: keyWord({ keys: ['⌘Z'], word: 'Undo', shortcut: 'Meta+Z', onPress: press, small: true }), ms: 0 });
}
