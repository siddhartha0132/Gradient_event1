/**
 * Monaco is bundled with the client (no CDN), so the editor works with the
 * internet cut. Only the Python tokenizer and the base editor worker are loaded.
 */
import { loader } from '@monaco-editor/react'
import * as monaco from 'monaco-editor/editor/editor.api'
import 'monaco-editor/languages/definitions/python/register'
import EditorWorker from 'monaco-editor/editor/editor.worker?worker'

self.MonacoEnvironment = { getWorker: () => new EditorWorker() }
loader.config({ monaco })

monaco.editor.defineTheme('iron', {
  base: 'vs-dark',
  inherit: true,
  rules: [
    { token: 'keyword', foreground: 'e5243b' },
    { token: 'string', foreground: 'f5a524' },
    { token: 'number', foreground: '4b7bec' },
    { token: 'comment', foreground: '6b7480', fontStyle: 'italic' },
  ],
  colors: {
    'editor.background': '#0b0d0f',
    'editor.lineHighlightBackground': '#14181c',
    'editorLineNumber.foreground': '#3a424c',
    'editorCursor.foreground': '#e5243b',
  },
})

let moduleNames: string[] = []

/** Block modules the team has built, offered as completions in strategy.py. */
export function setModuleNames(names: string[]) {
  moduleNames = names
}

const RANDOM = ['random()', 'choice(seq)', 'randint(a, b)', 'uniform(a, b)', 'shuffle(seq)', 'sample(seq, k)']
const MATH = ['sqrt(x)', 'exp(x)', 'log(x)', 'floor(x)', 'ceil(x)', 'pi', 'e', 'inf']

monaco.languages.registerCompletionItemProvider('python', {
  triggerCharacters: ['.'],
  provideCompletionItems(model, position) {
    const word = model.getWordUntilPosition(position)
    const range = {
      startLineNumber: position.lineNumber,
      endLineNumber: position.lineNumber,
      startColumn: word.startColumn,
      endColumn: word.endColumn,
    }
    const before = model.getLineContent(position.lineNumber).slice(0, word.startColumn - 1)
    const Kind = monaco.languages.CompletionItemKind
    const members = (names: string[]) =>
      names.map((n) => ({ label: n, kind: Kind.Function, insertText: n.replace(/\(.*\)/, '($0)'), insertTextRules: 4, range }))
    if (before.endsWith('random.')) return { suggestions: members(RANDOM) }
    if (before.endsWith('math.')) return { suggestions: members(MATH) }
    return {
      suggestions: [
        ...moduleNames.map((name) => ({
          label: name,
          kind: Kind.Function,
          documentation: 'Your block module',
          insertText: `${name}(my_history, opp_history)`,
          range,
        })),
        {
          label: 'strategy',
          kind: Kind.Snippet,
          documentation: 'The function the engine calls every turn',
          insertText: 'def strategy(my_history, opp_history):\n\t${1:return "C"}',
          insertTextRules: 4,
          range,
        },
        { label: 'my_history', kind: Kind.Variable, insertText: 'my_history', documentation: 'Your moves so far, e.g. ["C", "D"]', range },
        { label: 'opp_history', kind: Kind.Variable, insertText: 'opp_history', documentation: "Your opponent's moves so far", range },
        { label: '"C"', kind: Kind.Constant, insertText: '"C"', documentation: 'Cooperate', range },
        { label: '"D"', kind: Kind.Constant, insertText: '"D"', documentation: 'Defect', range },
        { label: 'import random', kind: Kind.Module, insertText: 'import random', range },
        { label: 'import math', kind: Kind.Module, insertText: 'import math', range },
      ],
    }
  },
})

export { monaco }
