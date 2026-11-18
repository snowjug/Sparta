"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/cn";
import { Icon, type IconName } from "@/components/ui/icon";
import { Brand } from "@/components/brand/logo";
import { SystemProviderBadge } from "./provider-badge";
import { AccountChip } from "./auth-gate";
import { DisplayMenu } from "./display-menu";

interface NavItem {
  href: string;
  label: string;
  short: string;
  icon: IconName;
  /** Path prefixes that keep this item highlighted. */
  match: string[];
}

export const NAV_ITEMS: NavItem[] = [
  { href: "/", label: "Home", short: "Home", icon: "home", match: [] },
  { href: "/live", label: "Live call", short: "Live", icon: "wave", match: ["/live"] },
  { href: "/calls", label: "Call history", short: "History", icon: "history", match: ["/calls"] },
  { href: "/studio", label: "Assistant Studio", short: "Studio", icon: "sliders", match: ["/studio"] },
  { href: "/safety", label: "Safety Center", short: "Safety", icon: "shield-check", match: ["/safety"] },
  { href: "/simulator", label: "Simulator Lab", short: "Lab", icon: "flask", match: ["/simulator"] },
];

export function isActive(item: NavItem, pathname: string): boolean {
  if (item.href === "/") return pathname === "/";
  return item.match.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}

export function SideNav() {
  const pathname = usePathname();
  return (
    <aside className="sticky top-0 hidden h-dvh w-64 shrink-0 flex-col gap-6 border-r border-line px-4 py-6 lg:flex">
      <Link href="/" aria-label="Sparta home" className="inline-flex min-h-11 items-center px-2">
        <Brand />
      </Link>
      <nav aria-label="Primary" className="flex flex-1 flex-col gap-1">
        {NAV_ITEMS.map((item) => {
          const active = isActive(item, pathname);
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex min-h-11 items-center gap-3 rounded-2xl px-3 text-sm font-medium transition-colors",
                active ? "bg-accent-soft text-fg" : "text-muted hover:bg-raised hover:text-fg",
              )}
            >
              <Icon name={item.icon} size={20} className={active ? "text-accent" : undefined} />
              {item.label}
            </Link>
          );
        })}
      </nav>
      <p className="px-2 text-sm text-muted">Your calls. Your voice. Your shield.</p>
    </aside>
  );
}

export function BottomNav() {
  const pathname = usePathname();
  return (
    <nav
      aria-label="Primary"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-surface/95 pb-[env(safe-area-inset-bottom)] backdrop-blur-sm lg:hidden"
    >
      <ul className="mx-auto grid max-w-xl grid-cols-6">
        {NAV_ITEMS.map((item) => {
          const active = isActive(item, pathname);
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex min-h-14 flex-col items-center justify-center gap-0.5 rounded-xl text-xs font-medium transition-colors",
                  active ? "text-fg" : "text-muted",
                )}
              >
                <span className={cn("flex h-7 w-11 items-center justify-center rounded-full transition-colors", active && "bg-accent-soft text-accent")}>
                  <Icon name={item.icon} size={20} />
                </span>
                {item.short}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

export function TopBar({ minimal }: { minimal?: boolean }) {
  return (
    <header className="flex items-center justify-between gap-3 px-4 pt-3 sm:px-6 lg:px-10 lg:pt-5">
      <Link href="/" aria-label="Sparta home" className={cn("inline-flex min-h-11 items-center", !minimal && "lg:invisible")}>
        <Brand compact />
      </Link>
      <div className="flex items-center gap-2">
        <AccountChip />
        <SystemProviderBadge />
        <DisplayMenu />
      </div>
    </header>
  );
}
