/**
 * Blockly setup: the custom blocks, a toolbox filtered by the round's allowed
 * categories, and a theme matching the app. The client only edits layouts; the
 * server compiles them to Python and enforces the limits again.
 */
import * as Blockly from 'blockly/core'
import 'blockly/blocks'
import * as En from 'blockly/msg/en'

Blockly.setLocale(En as unknown as Record<string, string>)

import { AMBER, CATEGORY_INFO, RED, TEAL } from './categories'

Blockly.Extensions.register('ic_module_name', function (this: Blockly.Block) {
  const field = this.getField('NAME') as Blockly.FieldTextInput
  // Python-safe names: lowercase letters, digits and _, starting with a letter
  field.setValidator((value: string) => {
    const clean = value.toLowerCase().replace(/[^a-z0-9_]/g, '_').replace(/^[^a-z]+/, '').slice(0, 31)
    return clean || null
  })
})

const WHO = [
  ["opponent's", 'opp'],
  ['my', 'me'],
]

Blockly.common.defineBlocksWithJsonArray([
  {
    type: 'ic_module',
    message0: 'module %1 %2 %3',
    args0: [{ type: 'field_input', name: 'NAME', text: 'my_module' }, { type: 'input_dummy' }, { type: 'input_statement', name: 'BODY' }],
    colour: RED,
    extensions: ['ic_module_name'],
    tooltip: 'A helper your strategy can call as name(my_history, opp_history)',
  },
  {
    type: 'ic_return',
    message0: 'return %1',
    args0: [{ type: 'input_value', name: 'VALUE' }],
    previousStatement: null,
    colour: RED,
    tooltip: 'Give back a value and stop the module',
  },
  {
    type: 'ic_move',
    message0: '%1',
    args0: [{ type: 'field_dropdown', name: 'MOVE', options: [['cooperate', 'C'], ['defect', 'D']] }],
    output: 'Move',
    colour: RED,
    tooltip: 'A move: "C" or "D"',
  },
  {
    type: 'ic_last_move',
    message0: '%1 last move',
    args0: [{ type: 'field_dropdown', name: 'WHO', options: WHO }],
    output: 'Move',
    colour: AMBER,
    tooltip: 'The last move played, or nothing on the first turn',
  },
  {
    type: 'ic_count',
    message0: 'number of %1 in %2 last %3 moves',
    args0: [
      { type: 'field_dropdown', name: 'MOVE', options: [['defections', 'D'], ['cooperations', 'C']] },
      { type: 'field_dropdown', name: 'WHO', options: WHO },
      { type: 'field_number', name: 'LAST', value: 10, min: 0, max: 1000, precision: 1 },
    ],
    output: 'Number',
    colour: AMBER,
    tooltip: 'Count moves in recent history. 0 means the whole match so far',
  },
  { type: 'ic_turn', message0: 'turns played so far', output: 'Number', colour: AMBER, tooltip: 'How many turns have been played' },
  { type: 'ic_first_turn', message0: 'first turn?', output: 'Boolean', colour: AMBER, tooltip: 'True on the first turn of a match' },
  {
    type: 'ic_chance',
    message0: '%1 %% chance',
    args0: [{ type: 'field_number', name: 'PERCENT', value: 10, min: 0, max: 100 }],
    output: 'Boolean',
    colour: TEAL,
    tooltip: 'True this often, at random',
  },
  { type: 'ic_random', message0: 'random number 0 to 1', output: 'Number', colour: TEAL, tooltip: 'A random fraction' },
])

export function toolbox(categories: string[]): Blockly.utils.toolbox.ToolboxDefinition {
  const category = (name: string, colour: string, types: string[]) => ({
    kind: 'category',
    name,
    colour,
    contents: types.map((type) => ({ kind: 'block', type })),
  })
  return {
    kind: 'categoryToolbox',
    contents: [
      category('Moves', RED, ['ic_return', 'ic_move']),
      ...categories.filter((c) => CATEGORY_INFO[c]).map((c) => category(CATEGORY_INFO[c].label, CATEGORY_INFO[c].colour, CATEGORY_INFO[c].blocks)),
    ],
  }
}

export const theme = Blockly.Theme.defineTheme('iron', {
  name: 'iron',
  base: Blockly.Themes.Classic,
  componentStyles: {
    workspaceBackgroundColour: '#0b0d0f',
    toolboxBackgroundColour: '#121518',
    toolboxForegroundColour: '#d9dde2',
    flyoutBackgroundColour: '#1a1e23',
    flyoutForegroundColour: '#d9dde2',
    flyoutOpacity: 0.96,
    scrollbarColour: '#3a424c',
    insertionMarkerColour: '#ffffff',
    insertionMarkerOpacity: 0.3,
    cursorColour: '#e5243b',
  },
  fontStyle: { family: 'JetBrains Mono, monospace', size: 11 },
})

export type Layout = Record<string, unknown>

type BlockState = { type?: string; fields?: Record<string, unknown>; inputs?: Record<string, { block?: BlockState; shadow?: BlockState }>; next?: { block?: BlockState } }

function topBlocks(layout: Layout): BlockState[] {
  const blocks = (layout.blocks as { blocks?: BlockState[] } | undefined)?.blocks
  return Array.isArray(blocks) ? blocks : []
}

/** Every block in a layout, counted the same way as the server. */
export function countBlocks(layout: Layout): number {
  const walk = (b: BlockState | undefined): number => {
    if (!b) return 0
    let n = 1
    for (const slot of Object.values(b.inputs ?? {})) n += walk(slot.block) + walk(slot.shadow)
    return n + walk(b.next?.block)
  }
  return topBlocks(layout).reduce((n, b) => n + walk(b), 0)
}

export function moduleName(layout: Layout): string {
  const top = topBlocks(layout).find((b) => b.type === 'ic_module')
  return String(top?.fields?.NAME ?? 'module')
}

export function newModule(existing: string[]): Layout {
  let n = 1
  while (existing.includes(`module${n}`)) n++
  return {
    blocks: {
      languageVersion: 0,
      blocks: [{ type: 'ic_module', id: crypto.randomUUID(), x: 24, y: 24, deletable: false, fields: { NAME: `module${n}` } }],
    },
  }
}

export { Blockly, CATEGORY_INFO }
