# GitHub PR Explorer - React Frontend

Modern React 18 + TypeScript frontend with Matrix UI design system.

## Development

```bash
# Install dependencies
npm install

# Start dev server (proxies to Flask backend on :5050)
npm run dev

# Visit http://localhost:3000
```

## Production Build

```bash
# Build for production
npm run build

# Preview production build
npm run preview
```

## Tech Stack

- **Framework**: React 18 + TypeScript
- **Build Tool**: Vite
- **State Management**: Zustand
- **Styling**: CSS with Matrix design tokens
- **Markdown**: react-markdown + remark-gfm

## Project Structure

```
src/
├── main.tsx              # Entry point
├── App.tsx               # Root component
├── api/                  # API client and types
├── stores/               # Zustand state stores
├── components/           # React components
├── hooks/                # Custom hooks
├── utils/                # Utility functions
└── styles/               # CSS files
```

## Matrix Design System

The UI uses the Matrix design system with:
- Dark-first theme (default)
- Light theme via `.matrix-light` class
- CSS custom properties (`--mx-*`)
- Inter font (UI) + JetBrains Mono (code)
