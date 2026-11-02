/** Block categories, kept apart from Blockly so screens can show them without loading the editor. */
export const RED = '#c0392b'
export const AMBER = '#d68910'
export const BLUE = '#3867d6'
export const GREEN = '#20a35a'
export const TEAL = '#16a085'

export const CATEGORY_INFO: Record<string, { label: string; colour: string; blocks: string[] }> = {
  logic: {
    label: 'Logic',
    colour: BLUE,
    blocks: ['controls_if', 'controls_ifelse', 'logic_compare', 'logic_operation', 'logic_negate', 'logic_boolean'],
  },
  history: { label: 'History', colour: AMBER, blocks: ['ic_last_move', 'ic_count', 'ic_turn', 'ic_first_turn'] },
  math: { label: 'Math', colour: GREEN, blocks: ['math_number', 'math_arithmetic'] },
  chance: { label: 'Chance', colour: TEAL, blocks: ['ic_chance', 'ic_random'] },
}
