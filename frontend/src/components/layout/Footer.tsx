export function Footer() {
  const currentYear = new Date().getFullYear()

  return (
    <footer className="mx-footer">
      <div className="mx-footer__content">
        <p className="mx-footer__text">
          GitHub PR Explorer · Powered by{' '}
          <a
            href="https://cli.github.com/"
            target="_blank"
            rel="noopener noreferrer"
            className="mx-footer__link"
          >
            GitHub CLI
          </a>{' '}
          &{' '}
          <a
            href="https://www.anthropic.com/claude"
            target="_blank"
            rel="noopener noreferrer"
            className="mx-footer__link"
          >
            Claude
          </a>
        </p>
        <p className="mx-footer__copyright">© {currentYear} · Matrix UI Design</p>
      </div>
    </footer>
  )
}
