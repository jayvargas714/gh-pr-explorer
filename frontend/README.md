# GitHub PR Explorer - React Frontend

Modern React 18 frontend for GitHub PR Explorer, built with TypeScript, Vite, Zustand, and Matrix UI design system.

## Tech Stack

- **React 18** - UI library with Composition API
- **TypeScript** - Type-safe JavaScript
- **Vite** - Fast build tool and dev server
- **Zustand** - Lightweight state management
- **React Markdown** - Markdown rendering
- **Matrix UI** - Custom design system with CSS custom properties

## Prerequisites

- Node.js 18+ and npm
- Flask backend running on `http://127.0.0.1:5050`

## Installation

\`\`\`bash
cd frontend
npm install
\`\`\`

## Development

Start the dev server with hot module replacement:

\`\`\`bash
npm run dev
\`\`\`

The frontend will run on \`http://localhost:3000\` with automatic proxy to the Flask backend on port 5050.

## Production Build

Build the optimized production bundle:

\`\`\`bash
npm run build
\`\`\`

The build output will be in the \`dist/\` directory.

## Features

### Pull Requests View
- Client-side pagination (20 PRs per page)
- 40+ filter properties across 5 tabs
- Branch divergence indicators
- Code review integration

### Analytics View (4 Sub-tabs)
- Developer stats, PR lifecycle, code activity, review responsiveness

### CI/Workflows View
- Workflow run history with filters and statistics

### Merge Queue & Reviews
- Queue management with notes
- Code review system with history

## State Management

Uses Zustand with 9 domain-sliced stores for clean state management.

## Matrix UI Design System

Custom design system with CSS custom properties for theming, dark/light mode support.

See full documentation in parent directory.
