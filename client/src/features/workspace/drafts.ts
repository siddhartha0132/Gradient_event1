/** Drafts are autosaved to IndexedDB so a reload or crash never loses work. */
import { get, set } from 'idb-keyval'
import type { Layout } from '../blocks/blocks'

/** What a team builds: hand-written code that defines strategy, plus block modules. */
export type Agent = { hand_code: string; modules: Layout[] }

const key = (teamId: string) => `draft:${teamId}`

export async function loadDraft(teamId: string): Promise<Agent | undefined> {
  try {
    const draft = await get<Agent | string>(key(teamId))
    // Drafts from before block modules were plain code
    return typeof draft === 'string' ? { hand_code: draft, modules: [] } : draft
  } catch {
    return undefined
  }
}

export async function saveDraft(teamId: string, agent: Agent) {
  try {
    await set(key(teamId), agent)
  } catch {
    // storage can be unavailable (private window); the server keeps every submitted version
  }
}

export const TEMPLATE = `import random


def strategy(my_history, opp_history):
    """Called once per turn. Return "C" to cooperate or "D" to defect.

    my_history and opp_history are lists of the moves played so far.
    Block modules you build are functions you can call here,
    for example: if my_module(my_history, opp_history): ...
    """
    if not opp_history:
        return "C"
    return opp_history[-1]
`
