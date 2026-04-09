import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    rules: {
      // Pre-existing: many `any` annotations in this codebase — warn for visibility,
      // do not fail CI. Aim to eliminate these gradually in future passes.
      '@typescript-eslint/no-explicit-any': 'warn',

      // Pre-existing: unused variables.
      // - caughtErrors:'none' → stop flagging `catch (e) {}` where e is unused
      // - *IgnorePattern '^_'  → permit the intentional-ignore underscore convention
      // - destructuredArrayIgnorePattern '^_' → covers `const [_, b] = arr`
      '@typescript-eslint/no-unused-vars': ['error', {
        argsIgnorePattern: '^_',
        varsIgnorePattern: '^_',
        destructuredArrayIgnorePattern: '^_',
        caughtErrors: 'none',
      }],

      // Pre-existing: many empty catch blocks in this codebase.
      // allowEmptyCatch stops errors on `catch (e) {}` patterns.
      'no-empty': ['warn', { allowEmptyCatch: true }],

      // Pre-existing: some files export both components and helpers.
      // Downgraded to warn — not a runtime bug, just a fast-refresh hint.
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],

      // Pre-existing: a few standalone expression statements exist.
      // Downgraded to warn so they surface without blocking CI.
      '@typescript-eslint/no-unused-expressions': 'warn',

      // Pre-existing: react-hooks v7 added 15+ React-Compiler-oriented rules.
      // This codebase does not use the React Compiler, so these advanced constraints
      // produce many false positives. Downgrade all v7-new rules to warn so that
      // the classic rules-of-hooks / exhaustive-deps remain as errors.
      'react-hooks/set-state-in-effect': 'warn',
      'react-hooks/immutability': 'warn',
      'react-hooks/purity': 'warn',
      'react-hooks/static-components': 'warn',
      'react-hooks/use-memo': 'warn',
      'react-hooks/component-hook-factories': 'warn',
      'react-hooks/preserve-manual-memoization': 'warn',
      'react-hooks/incompatible-library': 'warn',
      'react-hooks/globals': 'warn',
      'react-hooks/refs': 'warn',
      'react-hooks/error-boundaries': 'warn',
      'react-hooks/set-state-in-render': 'warn',
      'react-hooks/unsupported-syntax': 'warn',
      'react-hooks/config': 'warn',
      'react-hooks/gating': 'warn',
    },
  },
])
