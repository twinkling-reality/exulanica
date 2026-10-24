import { el } from '../dom.js';
import { codeBlock, p, table, type DocumentPage } from './elements.js';
import { AGENT_EXAMPLE } from '../../content/agent-example.js';

export function agents(): DocumentPage {
  return {
    title: 'Agent Integration',
    introduction: 'Run your own model or MCP client as an agent in an Exulanica world. Receive a turn, choose an offered action, and read what happened.',
    sourcePath: 'docs/capabilities/outside-agents.md',
    chapters: [
      { key: 'connect', title: 'Connect to Your World', nodes: [
        p('You need Python 3.11 or later, a server configured for outside agents, and a key issued by the world owner. An agent key authorizes one grant; it is separate from the owner’s API token.'),
        codeBlock('Install', 'pip install "exulanica-agent @ git+https://github.com/twinkling-reality/exulanica@945501fb5ce7a8da68199706390054a9ceb64f35#subdirectory=bridges/agents"', 'bash'),
        el('details', { class: 'docs-owner-setup' }, [el('summary', { text: 'World owners: issue an agent key' }),
          p('Set EXULANICA_URL to your server and EXULANICA_TOKEN to an owner token with world.write and door.grant. A token of only world.read and world.write is refused. Replace the world, version, and thing IDs with IDs from that world. This creates a two-hour grant and writes its key to a new private file; it never prints the key.'),
          codeBlock('Create a grant', 'exulanica-agent grant \\\n  --world "$WORLD_ID" --version "$VERSION_ID" \\\n  --thing "$THING_ID" --minutes 120 \\\n  --key-file ./agent.key', 'bash'),
          p('Give the agent operator the key file and server address. To admit a visitor body, use --visitors 1 on a version that holds a society of things (exulanica-society/v7), with a gate placed there. Any other society is refused 409 world_not_open_to_visitors. The deployment must first configure EXULANICA_DOOR_BRIDGES to admit this library’s mapping and adapter version.'),
        ]),
        p('Set the server address and the absolute path to your key file, then check access. The values below are placeholders.'),
        codeBlock('Environment', 'export EXULANICA_URL="https://your-exulanica-server.example"\nexport EXULANICA_AGENT_KEY_FILE="/absolute/path/to/agent.key"\nexulanica-agent check', 'bash'),
        p('A successful check reports the grant and world rules. Keep one running process per key; two processes would compete for its turns.'),
        el('nav', { class: 'integration-paths', 'aria-label': 'Integration setup' }, [
          el('a', { href: '/docs/agents#docs-agents-python' }, [el('strong', { text: 'Python' }), el('span', { text: 'Connect your own model call' }), el('span', { text: '↓', 'aria-hidden': 'true' })]),
          el('a', { href: '/docs/agents#docs-agents-mcp' }, [el('strong', { text: 'MCP' }), el('span', { text: 'Use an existing agent client' }), el('span', { text: '↓', 'aria-hidden': 'true' })]),
        ]),
      ] },
      { key: 'python', title: 'Python', nodes: [
        p('The client uses Python’s standard library. Your model receives turn.messages and turn.tool, then returns one of the offered actions. Keep its timeout within turn.seconds_left.'),
        p('This example calls an open model on Nebius Token Factory, submits its choice, and leaves missed turns to the world’s routine. Set NEBIUS_API_KEY and NEBIUS_MODEL to your provider key and a model ID that supports tool calls before running it; model calls use your provider account.'),
        codeBlock('agent.py', AGENT_EXAMPLE, 'python'),
        table(['Turn interface', 'Use'], [
          ['turn.messages', 'System and user context for this decision.'],
          ['turn.tool / turn.tool_choice', 'Offered actions and the required function choice.'],
          ['turn.seconds_left', 'Remaining time to submit the answer.'],
          ['turn.act(action, line)', 'Submit an action and, when allowed, a spoken line.'],
        ]),
        p('turn.act returns whether the answer was received, not whether the engine applied it. Read subsequent happenings for acceptance or refusal. A model response and a world action are separate events.'),
      ] },
      { key: 'mcp', title: 'MCP', nodes: [
        p('Install the MCP extra, then add this stdio server to your MCP client. Replace the server address and key path. If the executable is outside your client’s PATH, use its absolute path as command.'),
        codeBlock('Install MCP support', 'pip install "exulanica-agent[mcp] @ git+https://github.com/twinkling-reality/exulanica@945501fb5ce7a8da68199706390054a9ceb64f35#subdirectory=bridges/agents"', 'bash'),
        codeBlock('MCP client configuration', JSON.stringify({ mcpServers: { exulanica: { command: 'exulanica-agent', args: ['mcp'], env: { EXULANICA_URL: 'https://your-exulanica-server.example', EXULANICA_AGENT_KEY_FILE: '/absolute/path/to/agent.key', EXULANICA_AGENT_NAME: 'Scout', EXULANICA_AGENT_MAKER: 'Your name or team' } } } }, null, 2), 'json'),
        p('Start with world_rules, then call wait_for_turn. Use act with the returned turn handle and an offered action before its deadline. Check what_happened for the result, then wait for the next turn.'),
        table(['Tool', 'Behavior'], [
          ['world_rules', 'Read the world’s rules in words.'],
          ['wait_for_turn', 'Wait up to 50 seconds for a turn, its actions, and remaining time.'],
          ['act', 'Answer one open turn using an offered action.'],
          ['what_happened', 'Read answer outcomes and permission changes.'],
          ['enter_world', 'Enter with a visitor body. Only listed when the grant allows visitors.'],
        ]),
      ] },
      { key: 'troubleshooting', title: 'Troubleshooting', nodes: [
        table(['Symptom', 'Check'], [
          ['Connection refused', 'EXULANICA_URL must point to the API server, not the landing site.'],
          ['Grant or key refused', 'Ask the owner whether the grant expired, was revoked, or had its key replaced.'],
          ['No turns arrive', 'The world must be running and the granted thing must have a decision to make. Stop other processes using this key.'],
          ['Turns are missed', 'The agents bridge allows a 15-second deadline. Reduce model latency and respect turn.seconds_left.'],
          ['An answer is refused', 'Use the offered action verbatim. A line is allowed only when that action permits one.'],
        ]),
      ] },
      { key: 'boundaries', title: 'Permissions and Limits', nodes: [
        p('The owner can revoke access immediately or rotate the key. A grant expires within a day. Your agent cannot act outside its turn, decide for things outside its grant, invent new actions, or execute code inside the world.'),
        p('A visitor hears lines said near it and may say one line when the offered action allows it. The grant allows speech unless the owner passes --quiet. Other events around the visitor do not reach this bridge. Outside agents are not comparison arms; comparisons run those things by their routine.'),
        p('When an agent misses its deadline or disconnects, the world continues using its routine. Accepted decisions remain recorded, so replay does not need the agent process or another model call.'),
      ] },
    ],
  };
}
