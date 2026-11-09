"use client";

import Link from "next/link";
import { useConfig } from "@/components/ConfigProvider";
import { IconGithub } from "@/components/icons";
import { DemoBadge } from "@/components/ui";
import { site } from "@/config/site";

export function Logo() {
  return (
    <span className="inline-flex items-center gap-2.5">
      <span aria-hidden="true" className="relative inline-block h-6 w-5 rounded-[4px] border-[1.5px] border-ink">
        <span className="absolute left-[3px] right-[3px] top-[5px] h-[1.5px] bg-ink" />
        <span className="absolute left-[3px] right-[6px] top-[9px] h-[1.5px] bg-ink" />
        <span className="absolute -bottom-[1.5px] -right-[1.5px] h-2.5 w-2.5 rounded-[3px] bg-accent" />
      </span>
      <span className="text-[15px] font-semibold tracking-tight">{site.productName}</span>
    </span>
  );
}

export function Header() {
  const config = useConfig();
  return (
    <header className="border-b border-line">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-3 focus:z-50 focus:rounded-lg focus:bg-background focus:px-3 focus:py-2"
      >
        Skip to content
      </a>
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between gap-4 px-4 sm:px-6">
        <Link href="/" className="rounded-md" aria-label={`${site.productName} home`}>
          <Logo />
        </Link>
        <nav className="flex items-center gap-1 text-sm sm:gap-3">
          {config?.demo_mode && (
            <span className="hidden sm:inline-flex">
              <DemoBadge />
            </span>
          )}
          {config && !config.demo_mode && (
            <span className="hidden font-mono text-xs text-muted sm:inline">
              {config.provider === "anthropic" ? "Claude" : "OpenAI"} {config.model}
            </span>
          )}
          <Link href="/" className="rounded-md px-2 py-1.5 text-muted hover:text-ink">
            Home
          </Link>
          <Link href="/#checks" className="rounded-md px-2 py-1.5 text-muted hover:text-ink">
            How it checks
          </Link>
          {site.repoUrl ? (
            <a
              href={site.repoUrl}
              className="inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-muted hover:text-ink"
            >
              <IconGithub size={16} />
              <span className="hidden sm:inline">Code</span>
            </a>
          ) : null}
        </nav>
      </div>
    </header>
  );
}

export function Footer() {
  return (
    <footer className="mt-16 border-t border-line">
      <div className="mx-auto flex max-w-7xl flex-col gap-2 px-4 py-6 text-sm text-muted sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <p>
          Built by{" "}
          <a href={site.portfolioUrl} className="font-medium text-ink underline-offset-4 hover:underline">
            {site.author}
          </a>
          . Sample businesses and documents are fictional.
        </p>
        <a href={site.githubUrl} className="inline-flex items-center gap-1.5 hover:text-ink">
          <IconGithub size={15} /> GitHub
        </a>
      </div>
    </footer>
  );
}
