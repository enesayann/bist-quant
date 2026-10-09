import { stockPath, DEMO_MODE } from "../market/mode";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import {
  Activity,
  ArrowUpRight,
  BarChart3,
  ChevronRight,
  FlaskConical,
  LayoutDashboard,
  Menu,
  PanelLeftClose,
  Search,
  Send,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Wallet,
  X,
  type LucideIcon,
} from "lucide-react";
import { useDashboard } from "../data/context";
import { Badge, Button } from "./ui";

const navigation: Array<{
  label: string;
  path: string;
  icon: LucideIcon;
  group?: string;
}> = [
  { label: "Overview", path: "/", icon: LayoutDashboard },
  { label: "Market Scanner", path: "/scanner", icon: SlidersHorizontal },
  { label: "Positions", path: "/positions", icon: Wallet },
  { label: "Signals", path: "/signals", icon: Activity },
  { label: "Backtests", path: "/backtests", icon: BarChart3 },
  {
    label: "Daily Strategy",
    path: "/research/daily",
    icon: FlaskConical,
    group: "Research",
  },
  { label: "Intraday Strategy", path: "/research/intraday", icon: Activity },
  { label: "Telegram", path: "/telegram", icon: Send, group: "System" },
  { label: "Settings", path: "/settings", icon: Settings2 },
];
export function AppSidebar({
  collapsed,
  toggle,
  mobileOpen,
  closeMobile,
}: {
  collapsed: boolean;
  toggle(): void;
  mobileOpen: boolean;
  closeMobile(): void;
}) {
  const { activity } = useDashboard();
  const firstLink = useRef<HTMLAnchorElement>(null);
  useEffect(() => {
    if (mobileOpen) firstLink.current?.focus();
  }, [mobileOpen]);
  return (
    <>
      {mobileOpen && (
        <button
          className="sidebar-scrim"
          onClick={closeMobile}
          aria-label="Close navigation"
        />
      )}
      <aside
        className={`sidebar ${collapsed ? "collapsed" : ""} ${mobileOpen ? "mobile-open" : ""}`}
        aria-label="Main navigation"
        role={mobileOpen ? "dialog" : undefined}
        aria-modal={mobileOpen ? true : undefined}
        onKeyDown={(event) => {
          if (!mobileOpen || event.key !== "Tab") return;
          const controls = Array.from(
            event.currentTarget.querySelectorAll<HTMLElement>("a, button"),
          ).filter((element) => element.offsetParent !== null);
          const first = controls[0],
            last = controls.at(-1);
          if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last?.focus();
          }
          if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first?.focus();
          }
        }}
      >
        <Link
          className="brand"
          to="/"
          aria-label="BIST Quant overview"
          ref={firstLink}
          onClick={closeMobile}
        >
          <span className="brand-mark">
            <BarChart3 size={22} strokeWidth={1.8} />
          </span>
          <span className="brand-copy">
            <strong>
              BIST <span>Quant</span>
            </strong>
            <small>RESEARCH WORKSPACE</small>
          </span>
        </Link>
        <div className="workspace">
          <span className="workspace-avatar">BQ</span>
          <div>
            <strong>Paper workspace</strong>
            <small>Local research environment</small>
          </div>
          <ChevronRight size={14} />
        </div>
        <nav>
          {navigation.map(({ label, path, icon: Icon, group }) => (
            <div key={path}>
              {group && <div className="nav-group">{group}</div>}
              <NavLink
                end={path === "/"}
                to={path}
                title={label}
                aria-label={label}
                className={({ isActive }) =>
                  `nav-link ${isActive ? "active" : ""}`
                }
                onClick={closeMobile}
              >
                <Icon size={18} strokeWidth={1.7} />
                <span>{label}</span>
                {path === "/signals" && (
                  <small className="nav-count">{activity.length}</small>
                )}
              </NavLink>
            </div>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="connection">
            <ShieldCheck size={17} />
            <div>
              <strong>Read-only workspace</strong>
              <small>
                {DEMO_MODE
                  ? "Demo market mode"
                  : "Provider data · Demo portfolio"}
              </small>
            </div>
          </div>
          <Button
            variant="ghost"
            className="collapse-button"
            onClick={toggle}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            {collapsed ? (
              <ChevronRight size={18} />
            ) : (
              <>
                <PanelLeftClose size={17} />
                <span>Collapse sidebar</span>
              </>
            )}
          </Button>
          <Button
            variant="ghost"
            className="mobile-close"
            onClick={closeMobile}
          >
            <X size={17} />
            Close navigation
          </Button>
        </div>
      </aside>
    </>
  );
}
export function TopHeader({ openMobile }: { openMobile(): void }) {
  const { stocks } = useDashboard();
  const location = useLocation();
  const apiPage =
    location.pathname.startsWith("/stocks/") &&
    new URLSearchParams(location.search).get("demo") !== "1";
  const [query, setQuery] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  const current =
    navigation.find((item) => item.path === location.pathname)?.label ??
    (location.pathname.startsWith("/stocks/") ? "Stock research" : "Workspace");
  function openSearch() {
    setQuery("");
    dialog.current?.showModal();
  }
  useEffect(() => {
    const handle = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        openSearch();
      }
    };
    window.addEventListener("keydown", handle);
    return () => window.removeEventListener("keydown", handle);
  }, []);
  return (
    <header className="top-header">
      <div className="breadcrumb">
        <Button
          className="mobile-menu"
          variant="ghost"
          aria-label="Open navigation"
          onClick={openMobile}
        >
          <Menu size={20} />
        </Button>
        <span>Workspace</span>
        <ChevronRight size={13} />
        <strong>{current}</strong>
      </div>
      <div className="header-actions">
        <Button
          variant="ghost"
          className="search-trigger"
          onClick={openSearch}
          aria-label="Search tickers"
          title="Search tickers (Ctrl+K)"
        >
          <Search size={16} />
          <span>Search ticker</span>
          <kbd>⌘ K</kbd>
        </Button>
        <span className="header-divider" />
        <Badge tone="accent">
          <span className="status-dot" />
          {DEMO_MODE || new URLSearchParams(location.search).get("demo") === "1"
            ? "Demo data"
            : apiPage
              ? "Market / analysis"
              : "Provider data"}
        </Badge>
        <span
          className="profile-avatar"
          title="Local paper workspace"
          aria-label="Local paper workspace"
        >
          BQ
        </span>
      </div>
      <dialog
        ref={dialog}
        className="search-dialog"
        aria-labelledby="search-title"
        onClick={(event) => {
          if (event.target === event.currentTarget) dialog.current?.close();
        }}
      >
        <div className="dialog-heading">
          <h2 id="search-title">Find a ticker</h2>
          <Button
            variant="ghost"
            aria-label="Close search"
            onClick={() => dialog.current?.close()}
          >
            <X size={18} />
          </Button>
        </div>
        <label className="search-input">
          <Search size={17} />
          <input
            autoFocus
            aria-label="Search by ticker or company"
            placeholder="Ticker or company name…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <div className="search-results">
          {stocks
            .filter((stock) =>
              `${stock.ticker} ${stock.name}`
                .toLowerCase()
                .includes(query.toLowerCase()),
            )
            .map((stock) => (
              <Link
                key={stock.ticker}
                to={stockPath(stock.ticker)}
                onClick={() => dialog.current?.close()}
              >
                <span>
                  <strong>{stock.ticker}</strong>
                  <small>{stock.name}</small>
                </span>
                <ArrowUpRight size={16} />
              </Link>
            ))}
          {stocks.every(
            (stock) =>
              !`${stock.ticker} ${stock.name}`
                .toLowerCase()
                .includes(query.toLowerCase()),
          ) && (
            <p className="empty-copy">No matching ticker in the demo basket.</p>
          )}
        </div>
        <div className="dialog-footer">
          10 BIST tickers · Offline examples <kbd>ESC</kbd>
        </div>
      </dialog>
    </header>
  );
}
export function PageHeader({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      <div className="page-heading-actions">{children}</div>
    </div>
  );
}
export function AppLayout() {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();
  const menuFocus = useRef<HTMLElement | null>(null);
  function closeMobile() {
    setMobileOpen(false);
    menuFocus.current?.focus();
  }
  useEffect(() => {
    if (!mobileOpen) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const handle = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeMobile();
    };
    window.addEventListener("keydown", handle);
    return () => {
      document.body.style.overflow = previous;
      window.removeEventListener("keydown", handle);
    };
  }, [mobileOpen]);
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [location.pathname]);
  return (
    <div className={`app-shell ${collapsed ? "sidebar-collapsed" : ""}`}>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <AppSidebar
        collapsed={collapsed}
        toggle={() => setCollapsed(!collapsed)}
        mobileOpen={mobileOpen}
        closeMobile={closeMobile}
      />
      <div className="main-shell" inert={mobileOpen}>
        <TopHeader
          openMobile={() => {
            menuFocus.current = document.activeElement as HTMLElement;
            setMobileOpen(true);
          }}
        />
        <main id="main" tabIndex={-1}>
          <Outlet />
        </main>
        <footer className="app-footer">
          <span>
            BIST Quant <span className="footer-dot">·</span> Quant Research &
            Paper Trading
          </span>
          <span>
            On-demand analysis <span className="footer-dot">·</span> No
            brokerage connection
          </span>
        </footer>
      </div>
    </div>
  );
}
