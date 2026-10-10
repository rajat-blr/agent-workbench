import assert from 'node:assert/strict'
import { test } from 'node:test'
import { fileCaution, stageSelection } from '../src/gitReview.ts'

const status = {
  files: [
    { path: 'src/change.ts', unstaged: true },
    { path: '.env', unstaged: true },
    { path: 'build/output.js', unstaged: true },
    { path: 'already-staged.txt', unstaged: false },
    { path: 'line\nbreak.txt', unstaged: true },
  ],
}

test('staging requires explicit selection and never expands to other files', () => {
  assert.throws(() => stageSelection(status, []))
  const selected = ['src/change.ts']
  const paths = stageSelection(status, selected)
  assert.deepEqual(paths, selected)
  assert.notEqual(paths, selected)
  assert.ok(!paths.includes('.env') && !paths.includes('build/output.js'))
  assert.deepEqual(stageSelection(status, ['line\nbreak.txt']), ['line\nbreak.txt'])
})

test('staging rejects stale selections, duplicates, directories, and already-staged files', () => {
  for (const selected of [['missing'], ['.'], ['already-staged.txt'], ['src/change.ts', 'src/change.ts']]) {
    assert.throws(() => stageSelection(status, selected))
  }
})

test('secret/generated path hints are advisory and do not silently select files', () => {
  for (const path of ['.env', 'nested/.env.local', 'keys/server.pem', 'build/output.js', 'dist/index.html']) {
    assert.ok(fileCaution(path))
  }
  assert.equal(fileCaution('src/environment.ts'), null)
  assert.equal(fileCaution('src/change.ts'), null)
  assert.deepEqual(stageSelection(status, ['.env']), ['.env'])
})
