import { el } from '../dom.js';
import { entries, onward, p, source, steps, type DocumentPage } from './elements.js';
export function models(): DocumentPage {
  return { title: 'Models and Decisions', introduction: 'Choose who decides for a supported role. The world validates every proposal before it takes effect.', sourcePath: 'docs/decision-roles-contract.md', chapters: [
    { key: 'roles', title: 'Give a Model a Role', nodes: [p('People, animals, vehicles, and other decision-makers can act in a world. A decision role is the subset a model may decide for.'), p('The role registry supports a person and a junction signal. Discover the roles your world offers rather than assuming every agent can be assigned a model. Model-run vehicles, weather, and economies are product targets without supported role contracts.'), entries([{ label: 'Routine', detail: 'Runs without model calls. Supplies a valid decision when a model or outside agent cannot answer.' }, { label: 'Chosen model', detail: 'Receives the role’s context and offered choices through the configured provider.' }, { label: 'Outside agent', detail: 'Answers offered turns under a grant issued by the world owner.' }])] },
      { key: 'models', title: 'Choose a Model', nodes: [
        p('People follow their routines until you assign a model. Your installation determines which models are available and how many people one choice can cover.'),
        steps('Open the controls for the world’s people and select a model from Decided by.', 'Choose the people you want that model to decide for.', 'Select Use for the chosen people. The model takes over from their next decision.'),
        el('figure', { class: 'docs-figure' }, [el('img', { src: '/product/model-selection.jpg', alt: 'Four people selected under Decided by in the application.', width: '1280', height: '860', loading: 'lazy' }), el('figcaption', { text: 'A recorded session assigning a model to a group. Available models depend on your installation.' })]),
        p('The world checks each answer before applying it. An invalid or missing answer leaves the person with a valid routine decision. Inspect a person to see who decided their latest turn and the recorded reason.'),
      ] },
    { key: 'validation', title: 'Follow One Decision', nodes: [
        steps(
          'Observe. The role supplies context and the choices available at this decision point.',
          'Propose. The model returns an offered choice within its answering budget.',
          'Validate. The engine checks the proposal before applying it and records a refusal when it cannot apply.',
          'Record. The observation, the model, and the result stay available for inspection and replay.',
        ),
        p('A provider answer is not proof that the world applied it. Inspect the recorded outcome and reason.'),
      ] },
    { key: 'providers', title: 'Model Availability and Spending', nodes: [
        p('The installation’s model catalog, role requirements, provider credentials and spending authority determine availability. Choosing a model does not prove its host is ready.'),
        p('Live decisions call the configured provider. Replay reads stored decisions without another call. Configure your spending bound before starting a comparison.'),
        onward('/docs/self-hosting#docs-self-hosting-models', 'Installation'),
        onward('/docs/world-api/models', 'List Decision Roles'),
      ] },
    { key: 'extend', title: 'Connect a Model of Your Own', nodes: [p('Use Python or MCP to run an outside agent. The grant defines its subjects, expiration and permitted turns; your model runs outside the world and submits one offered action.'), onward('/docs/agents', 'Connect an outside agent'), source('docs/decision-roles-contract.md', 'Decision-role contract')] },
  ] };
}
export function comparisons(): DocumentPage {
  return { title: 'Comparisons and Replay', introduction: 'Change one model, keep the starting world fixed, and inspect what differs against a measured control.', sourcePath: 'docs/society-experiments.md', chapters: [
    { key: 'prepare', title: 'Before You Start', nodes: [p('Open a saved world with a society and available model controls. Decide which group you want to compare and what question its decisions can answer. Read the estimated cost and availability before setting a spending bound.'), p('Reading a saved comparison or replay does not ask a model. Starting a comparison does.'), onward('/docs/models', 'Choose models for a world')] },
      { key: 'compare', title: 'Compare Models', nodes: [
        p('Open Compare from the World menu or tool rail. Reading an existing comparison makes no new model calls. Starting a comparison asks the selected models and uses the spending bound you set.'),
        steps('Select the people to compare and the two models. Review availability, the planned runs, and the estimated cost.', 'Review the same-model control and seed settings. Set a spending bound before starting.', 'Follow the run’s progress. When results arrive, read the verdict before interpreting differences in the replay.', 'Use the shared timeline to follow the same minute on both sides. Select a person to inspect their decisions; open Every number from this comparison for scores, answer rates, cost, and timing.'),
        p('The application compares one simulated hour from the same starting world. Routine and waiting runs provide baselines; a repeated model supplies a control for variation. Different activity patterns can still produce no measured difference on the declared score.'),
      ] },
    { key: 'interpret', title: 'Read the Verdict', nodes: [
        p('The comparison names one of three results. Read that name before treating a visible difference as a model result.'),
        entries([
          { label: 'Measured difference', detail: 'The declared score distinguishes the arms beyond the same-model control for this comparison.' },
          { label: 'No measured difference', detail: 'The score does not establish a difference beyond the control. Visible activities may still differ.' },
          { label: 'Incomplete', detail: 'An unfinished arm or unmet acceptance condition cannot support a comparison verdict.' },
        ]),
        p('Inspect scores, answer rates, refusals, cost and timing together. A result applies to its world, group, duration, seeds and score; it does not establish that one model is better for every role.'),
      ] },
    { key: 'replay', title: 'Inspect and Replay Decisions', nodes: [p('Replay follows recorded decisions without contacting the models again. The same timeline lets you inspect what a person observed, which choice was proposed and what the engine applied.'), p('The browser starts and draws one-hour comparisons, because its start leaves the window unset and the route defaults to hour. A day is a supported window on the comparison routes and through the local command. A finished day has a verdict, as an hour does. A purposeful society is not compared over a day.'), onward('/docs/world-api/replay', 'Read recorded history through the API'), source('docs/society-experiments.md', 'Comparison definitions, scoring and commands')] },
  ] };
}
