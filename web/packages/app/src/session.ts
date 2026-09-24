/**
 * THE COMPOSITION ROOT, and the only file in this package permitted to name the mutation gate.
 *
 * `architecture-overview.md` 1.1: "graph-client is the only module permitted to mutate, and it
 * rejects any mutation whose proposal id is not in the pending proposal set. This is a runtime
 * check, not a lint rule."
 *
 * A composition root has to construct that gate, which means one file here has to import
 * `@exulanica/graph-client/mutations`. `.dependency-cruiser.cjs` names THIS FILE rather than this
 * package, so the rule stays as strong as it was: every other module in the app receives a
 * `commit` function and cannot reach the gate to go around it. If a second file in this package
 * ever imports the mutation entry point, the boundary check fails.
 *
 * **Nothing here decides whether a proposal is sound.** The gate refuses a proposal that is not
 * pending, one that expired against the current state version, and any tier 3 operation, and it
 * refuses them at the moment of the write. This file wires it up and hands out one function.
 *
 * **The token is never in a URL.** It is held by the transport and nowhere else, which is why
 * evidence is fetched as bytes and turned into a blob URL rather than being pointed at with an
 * `<img src>`: an `<img>` request would not carry the header, and moving the token into the
 * query string to fix that would put somebody's photograph library behind a value that ends up
 * in a proxy log.
 */

import type { GraphSnapshot, UpdateProposal } from '@exulanica/graph-client';
import { ExulanicaClient, Transport } from '@exulanica/graph-client';
import { ProposalGate, httpCommitTransport } from '@exulanica/graph-client/mutations';
import { CompanionSession } from '@exulanica/companion-runtime';

export interface SessionOptions {
  readonly baseUrl: string;
  readonly token: string;
  readonly csrfToken?: string;
  /** The open world's region for each photograph it holds, asked at every graph read. */
  readonly worldRegions?: () => ReadonlyMap<string, string> | undefined;
}

/**
 * What every other module in this package is given.
 *
 * Deliberately not the client and not the gate. A surface that held the gate could stage a
 * proposal and commit it in the same breath, which is the shape the confirmation requirement
 * exists to prevent; a surface that holds `stage` and `commit` separately cannot, because the
 * proposal has to be rendered between the two calls for the user to press anything.
 */
export interface Session {
  readonly client: ExulanicaClient;
  snapshot(): Promise<GraphSnapshot>;
  /** Stage a proposal for rendering. Writes nothing. */
  stage(proposal: UpdateProposal): void;
  discard(proposalId: string): void;
  /** The only write path. Throws `ProposalGateError` when the proposal may not commit. */
  commit(proposalId: string): Promise<number>;
  stateVersion(): number;
}

/** The session, and the snapshot opening it already paid for. */
export interface OpenedSession {
  readonly session: Session;
  readonly initial: GraphSnapshot;
  /**
   * The Companion's turn engine.
   *
   * Built HERE and nowhere else, for the same reason the gate is: `CompanionSession` takes the
   * gate directly, so any other module that constructed one would need the gate handed to it and
   * the invariant at the top of this file would be gone. Handing out the built session instead
   * keeps stage and commit as separate calls with a rendered confirmation between them, which is
   * the whole point.
   */
  readonly companion: CompanionSession;
}

export async function openSession(options: SessionOptions): Promise<OpenedSession> {
  const client = new ExulanicaClient(options);
  // The gate needs a state version to expire proposals against, and there is exactly one honest
  // source for it: the graph the session is about to render. Starting at zero would make every
  // proposal look current until the first refresh.
  const initial = await client.snapshot();
  const gate = new ProposalGate(
    httpCommitTransport(new Transport(options)),
    initial.stateVersion,
  );

  const session: Session = {
    client,
    snapshot: () => client.snapshot(),
    stage: (proposal) => gate.stage(proposal),
    discard: (proposalId) => gate.discard(proposalId),
    async commit(proposalId) {
      const result = await gate.commit(proposalId);
      return result.stateVersion;
    },
    stateVersion: () => gate.stateVersion,
  };
  const companion = new CompanionSession({ snapshot: initial, gate });
  return { session, initial, companion };
}
