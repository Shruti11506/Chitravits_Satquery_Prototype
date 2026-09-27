"use client"

import * as React from "react"
import { createPortal } from "react-dom"
import {
  SquarePen,
  Image as ImageIcon,
  Compass,
  Cpu,
  FolderKanban,
  Plus,
  GitCompare,
  BarChart3,
  Sparkles,
  Settings,
  Satellite,
  Waves,
  FileBarChart,
  User,
  MoreHorizontal,
  Share2,
  Clock,
  AlertCircle,
  RefreshCw,
  Pencil,
  Trash2,
  LogOut
} from "lucide-react"

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarTrigger,
  useSidebar
} from "@/components/ui/sidebar"
import { ChitravitsEmblem } from "./ui/ChitravitsLogo"
import {
  deleteConversation,
  getAnalysisHistory,
  listConversations,
  renameConversation,
  type Conversation,
  type HistoryItem as ApiHistoryItem,
  type ProfileUser
} from "../lib/apiClient"

interface UserHistorySidebarProps {
  onNewChat: () => void
  onSelectConversation: (conversation: Conversation) => void
  onSelectHistoryItem: (item: ApiHistoryItem) => void
  onConversationRenamed?: (conversation: Conversation) => void
  onConversationDeleted?: (conversationId: string) => void
  onNavigateScreen: (screenId: string) => void
  activeScreen: string
  activeConversationId?: string | null
  activeImageryId?: string | null
  refreshToken?: number
  /** The workspace profile from GET /profile; null while loading or if unavailable. */
  profileUser?: ProfileUser | null
  onOpenProfile?: () => void
  theme?: string
  onToggleTheme?: (e?: any) => void
  activeModel?: any
  projects?: any[]
  activeProjectId?: string | null
  onOpenProject?: (project: any) => void
  onOpenSettings: () => void
}

// One sidebar row. Conversations carry their stored title; legacy entries
// (requests made before conversations existed, one per image) are shown by
// their first query -- never by the uploaded filename -- and are read-only.
type SidebarEntry =
  | { kind: "conversation"; key: string; title: string; at: string; conversation: Conversation }
  | { kind: "legacy"; key: string; title: string; at: string; item: ApiHistoryItem }

type DateGroup = "today" | "yesterday" | "sevenDays" | "thirtyDays" | "older"

const GROUP_LABELS: Array<[DateGroup, string]> = [
  ["today", "Today"],
  ["yesterday", "Yesterday"],
  ["sevenDays", "Previous 7 Days"],
  ["thirtyDays", "Previous 30 Days"],
  ["older", "Older"]
]

function groupForDate(iso: string): DateGroup {
  const startOfToday = new Date()
  startOfToday.setHours(0, 0, 0, 0)
  const days = Math.floor((startOfToday.getTime() - new Date(iso).getTime()) / (1000 * 60 * 60 * 24)) + 1
  if (days <= 0) return "today"
  if (days === 1) return "yesterday"
  if (days < 7) return "sevenDays"
  if (days < 30) return "thirtyDays"
  return "older"
}

function initialsOf(name?: string | null): string {
  const parts = (name || "").trim().split(/\s+/).filter(Boolean)
  if (!parts.length) return "?"
  return (parts[0][0] + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase()
}

function planLabel(plan?: string | null): string {
  const value = plan || "free"
  return `${value.charAt(0).toUpperCase()}${value.slice(1)} Plan`
}

// Photo if the profile has one, otherwise its initials. Nothing is shown in
// place of a profile that hasn't loaded -- no placeholder identity.
function ProfileAvatar({ user, className }: { user?: ProfileUser | null; className: string }) {
  return (
    <div className={`${className} rounded-full bg-blue-600 text-white font-semibold flex items-center justify-center shrink-0 shadow-sm overflow-hidden`}>
      {user?.avatar_url
        ? <img src={user.avatar_url} alt="" className="w-full h-full object-cover" />
        : user ? initialsOf(user.display_name) : <User className="w-3.5 h-3.5" />}
    </div>
  )
}

// Small, uniform row icon picked from the title's keywords -- presentation
// only; every icon renders at the same size and muted color (see the
// "Sidebar rows" block in index.css).
function ConversationIcon({ title }: { title: string }) {
  if (/\b(sar|radar)\b/i.test(title)) return <Satellite aria-hidden="true" />
  if (/water|flood|river|lake|ndwi/i.test(title)) return <Waves aria-hidden="true" />
  if (/report|summary|dossier/i.test(title)) return <FileBarChart aria-hidden="true" />
  return <ImageIcon aria-hidden="true" />
}

function truncate(text: string, max = 60): string {
  if (!text) return ""
  return text.length > max ? text.slice(0, max - 1) + "…" : text
}

function buildEntries(conversations: Conversation[], history: ApiHistoryItem[]): SidebarEntry[] {
  const entries: SidebarEntry[] = conversations.map((conversation) => ({
    kind: "conversation",
    key: `c-${conversation.id}`,
    title: conversation.title,
    at: conversation.updated_at || conversation.created_at,
    conversation
  }))

  // history is newest first, so the last item seen per image is its first query.
  const legacyByImage = new Map<string, { latest: ApiHistoryItem; first: ApiHistoryItem }>()
  history
    .filter((item) => !item.conversation_id)
    .forEach((item) => {
      const existing = legacyByImage.get(item.imagery_id)
      if (existing) existing.first = item
      else legacyByImage.set(item.imagery_id, { latest: item, first: item })
    })
  legacyByImage.forEach(({ latest, first }, imageryId) => {
    entries.push({
      kind: "legacy",
      key: `l-${imageryId}`,
      title: truncate(first.query),
      at: latest.created_at,
      item: latest
    })
  })

  return entries.sort((a, b) => new Date(b.at).getTime() - new Date(a.at).getTime())
}

interface ConversationRowProps {
  entry: SidebarEntry
  isActive: boolean
  isMenuOpen: boolean
  onOpenMenu: (key: string | null) => void
  onSelect: (entry: SidebarEntry) => void
  onRename: (conversation: Conversation, title: string) => Promise<void>
  onDelete: (conversation: Conversation) => Promise<void>
}

function ConversationRow({ entry, isActive, isMenuOpen, onOpenMenu, onSelect, onRename, onDelete }: ConversationRowProps) {
  const [isEditing, setIsEditing] = React.useState(false)
  const [draft, setDraft] = React.useState(entry.title)
  const menuRef = React.useRef<HTMLDivElement>(null)
  const triggerRef = React.useRef<HTMLButtonElement>(null)
  const [menuPos, setMenuPos] = React.useState<{ top: number; left: number } | null>(null)

  // Portaled to <body> and positioned from the clicked row's rect -- the
  // sidebar's scroll container (overflow-auto) would otherwise clip an in-flow
  // popup. Opens just outside the sidebar's right edge, top-aligned with the
  // row; flips upward / to the left when the viewport has no room.
  const MENU_GAP = 8
  const VIEWPORT_MARGIN = 8

  const updateMenuPos = React.useCallback(() => {
    const trigger = triggerRef.current
    if (!trigger) return
    const triggerRect = trigger.getBoundingClientRect()
    const rowRect = (trigger.closest("li") ?? trigger).getBoundingClientRect()
    const sidebarRight = trigger.closest('[data-sidebar="sidebar"]')?.getBoundingClientRect().right ?? triggerRect.right
    // offsetWidth/Height ignore the zoom-in transform, so this is the settled size.
    const width = menuRef.current?.offsetWidth ?? 212
    const height = menuRef.current?.offsetHeight ?? 88
    const maxLeft = window.innerWidth - width - VIEWPORT_MARGIN
    const maxTop = window.innerHeight - height - VIEWPORT_MARGIN

    let left = Math.max(triggerRect.right, sidebarRight) + MENU_GAP
    if (left > maxLeft) left = triggerRect.left - MENU_GAP - width
    left = Math.min(Math.max(left, VIEWPORT_MARGIN), maxLeft)

    let top = rowRect.top
    if (top > maxTop) top = rowRect.bottom - height
    top = Math.min(Math.max(top, VIEWPORT_MARGIN), maxTop)

    setMenuPos({ top, left })
  }, [])

  React.useLayoutEffect(() => {
    if (!isMenuOpen) {
      setMenuPos(null)
      return
    }
    updateMenuPos()
    window.addEventListener("resize", updateMenuPos)
    window.addEventListener("scroll", updateMenuPos, true)
    return () => {
      window.removeEventListener("resize", updateMenuPos)
      window.removeEventListener("scroll", updateMenuPos, true)
    }
  }, [isMenuOpen, updateMenuPos])

  React.useEffect(() => {
    if (!isMenuOpen) return
    const close = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) onOpenMenu(null)
    }
    const closeOnEscape = (e: KeyboardEvent) => {
      if (e.key === "Escape") onOpenMenu(null)
    }
    document.addEventListener("mousedown", close)
    document.addEventListener("keydown", closeOnEscape)
    return () => {
      document.removeEventListener("mousedown", close)
      document.removeEventListener("keydown", closeOnEscape)
    }
  }, [isMenuOpen, onOpenMenu])

  const commitRename = async () => {
    setIsEditing(false)
    const title = draft.trim()
    if (entry.kind !== "conversation" || !title || title === entry.title) return
    await onRename(entry.conversation, title)
  }

  if (isEditing && entry.kind === "conversation") {
    return (
      <SidebarMenuItem>
        <input
          autoFocus
          value={draft}
          maxLength={120}
          onChange={(e) => setDraft(e.target.value)}
          onFocus={(e) => e.currentTarget.select()}
          onBlur={commitRename}
          onKeyDown={(e) => {
            if (e.key === "Enter") e.currentTarget.blur()
            if (e.key === "Escape") {
              setDraft(entry.title)
              setIsEditing(false)
            }
          }}
          aria-label="Conversation title"
          style={{ padding: "0 10px" }}
          className="w-full h-[38px] rounded-lg text-[14px] bg-[rgba(59,130,246,0.08)] text-sidebar-foreground outline-none ring-1 ring-blue-500/60"
        />
      </SidebarMenuItem>
    )
  }

  return (
    <SidebarMenuItem>
      <SidebarMenuButton
        onClick={() => onSelect(entry)}
        isActive={isActive}
        data-row="conversation"
        className="group/item"
        tooltip={entry.title}
      >
        <ConversationIcon title={entry.title} />
        <span className="truncate">{entry.title}</span>
      </SidebarMenuButton>

      {entry.kind === "conversation" && (
        <>
          <SidebarMenuAction
            ref={triggerRef}
            showOnHover
            data-state={isMenuOpen ? "open" : "closed"}
            onClick={(e) => {
              e.stopPropagation()
              onOpenMenu(isMenuOpen ? null : entry.key)
            }}
            title="Conversation options"
            aria-label="Conversation options"
          >
            <MoreHorizontal />
          </SidebarMenuAction>

          {isMenuOpen && createPortal(
            // Rendered hidden for one layout pass so its real size can be measured.
            // Explicit hsl(var(--sidebar-*)) colors: Tailwind 4 doesn't load
            // tailwind.config.js, so bg-sidebar / text-sidebar-* generate nothing
            // and the menu was see-through over the image viewer.
            // z-[200]: above the workspace header (100), below modals (999).
            // transition-none: duration-150 alone would transition `all`, sliding
            // the menu in from its hidden measuring spot at 0,0.
            <div
              ref={menuRef}
              role="menu"
              style={menuPos ? { top: menuPos.top, left: menuPos.left } : { top: 0, left: 0, visibility: "hidden" }}
              className="fixed z-[200] flex w-[212px] flex-col gap-1 rounded-[11px] border border-[rgba(148,163,184,0.28)] bg-[hsl(var(--sidebar-background))] p-2 shadow-[0_12px_30px_rgba(0,0,0,0.45),0_0_0_1px_rgba(59,130,246,0.05)] animate-in fade-in-0 zoom-in-95 duration-150 transition-none"
            >
              <button
                role="menuitem"
                className="flex h-11 w-full items-center gap-3 rounded-[8px] px-3.5 text-sm text-[hsl(var(--sidebar-foreground)/0.95)] transition-colors duration-100 hover:bg-blue-500/10"
                onClick={() => {
                  onOpenMenu(null)
                  setDraft(entry.title)
                  setIsEditing(true)
                }}
              >
                <Pencil className="w-4 h-4 text-[hsl(var(--sidebar-foreground)/0.7)]" />
                <span>Rename</span>
              </button>
              <button
                role="menuitem"
                className="flex h-11 w-full items-center gap-3 rounded-[8px] px-3.5 text-sm text-red-400/90 transition-colors duration-100 hover:bg-red-500/10 hover:text-red-400"
                onClick={() => {
                  onOpenMenu(null)
                  onDelete(entry.conversation)
                }}
              >
                <Trash2 className="w-4 h-4" />
                <span>Delete</span>
              </button>
            </div>,
            document.body
          )}
        </>
      )}
    </SidebarMenuItem>
  )
}

export function UserHistorySidebar({
  onNewChat,
  onSelectConversation,
  onSelectHistoryItem,
  onConversationRenamed,
  onConversationDeleted,
  onNavigateScreen,
  activeScreen,
  activeConversationId,
  activeImageryId,
  refreshToken,
  profileUser,
  onOpenProfile,
  theme,
  onToggleTheme,
  activeModel,
  projects,
  activeProjectId,
  onOpenProject,
  onOpenSettings
}: UserHistorySidebarProps) {
  // Real backend data ONLY -- see CLAUDE.md / backend README. No hardcoded
  // entries, and a failed fetch never falls back to stale/sample data.
  const [entries, setEntries] = React.useState<SidebarEntry[]>([])
  const [status, setStatus] = React.useState<"loading" | "ready" | "error">("loading")
  // The backend's own reason (e.g. backend not running, Supabase not
  // configured) -- shown under the error so setup problems aren't a mystery.
  const [errorDetail, setErrorDetail] = React.useState<string | null>(null)
  const [openMenuKey, setOpenMenuKey] = React.useState<string | null>(null)
  const { isMobile, setOpenMobile, setOpen } = useSidebar()
  const hasLoadedRef = React.useRef(false)

  const dismissSidebar = React.useCallback(() => {
    if (isMobile) {
      setOpenMobile(false)
    } else {
      setOpen(false)
    }
  }, [isMobile, setOpenMobile, setOpen])

  const [isProfileMenuOpen, setIsProfileMenuOpen] = React.useState(false)
  const profileTriggerRef = React.useRef<HTMLButtonElement>(null)
  const profileMenuRef = React.useRef<HTMLDivElement>(null)

  React.useEffect(() => {
    if (!isProfileMenuOpen) return
    const close = (e: MouseEvent) => {
      if (
        !profileMenuRef.current?.contains(e.target as Node) &&
        !profileTriggerRef.current?.contains(e.target as Node)
      ) {
        setIsProfileMenuOpen(false)
      }
    }
    const closeOnEscape = (e: KeyboardEvent) => {
      if (e.key === "Escape") setIsProfileMenuOpen(false)
    }
    document.addEventListener("mousedown", close)
    document.addEventListener("keydown", closeOnEscape)
    return () => {
      document.removeEventListener("mousedown", close)
      document.removeEventListener("keydown", closeOnEscape)
    }
  }, [isProfileMenuOpen])

  const fetchHistory = React.useCallback(() => {
    // Only the very first load shows "Loading…"; refreshes (e.g. a title
    // arriving) swap the list in place instead of flashing it away.
    if (!hasLoadedRef.current) setStatus("loading")
    Promise.all([listConversations(100), getAnalysisHistory(200)])
      .then(([conversations, history]) => {
        setEntries(buildEntries(conversations, history))
        setStatus("ready")
        hasLoadedRef.current = true
      })
      .catch((err) => {
        console.error("[SatQuery] Failed to load conversation history:", err)
        setEntries([])
        setErrorDetail((err as Error)?.message || null)
        setStatus("error")
        hasLoadedRef.current = false
      })
  }, [])

  React.useEffect(() => {
    fetchHistory()
  }, [fetchHistory, refreshToken])

  const handleItemClick = (entry: SidebarEntry) => {
    if (entry.kind === "conversation") onSelectConversation(entry.conversation)
    else onSelectHistoryItem(entry.item)
    dismissSidebar()
  }

  const handleRename = async (conversation: Conversation, title: string) => {
    // Optimistic: show the new title immediately, reconcile with the server.
    setEntries((prev) => prev.map((e) => (e.key === `c-${conversation.id}` ? { ...e, title } : e)))
    try {
      const updated = await renameConversation(conversation.id, title)
      onConversationRenamed?.(updated)
    } catch (err) {
      console.error("[SatQuery] Failed to rename conversation:", err)
      window.alert(`Could not rename conversation: ${(err as Error).message || "unknown error"}`)
    }
    fetchHistory()
  }

  const handleDelete = async (conversation: Conversation) => {
    const ok = window.confirm(
      `Delete "${conversation.title}"?\n\nThis permanently removes the conversation, its queries and its uploaded images.`
    )
    if (!ok) return
    try {
      await deleteConversation(conversation.id)
      onConversationDeleted?.(conversation.id)
    } catch (err) {
      console.error("[SatQuery] Failed to delete conversation:", err)
      window.alert(`Could not delete conversation: ${(err as Error).message || "unknown error"}`)
    }
    fetchHistory()
  }

  // A conversation is highlighted on the landing screen too: New Chat opens a
  // real (still empty) conversation there, so the sidebar shows that record
  // rather than a frontend-only placeholder.
  const isEntryActive = (entry: SidebarEntry) =>
    entry.kind === "conversation"
      ? (activeScreen === "workspace" || activeScreen === "landing") &&
        entry.conversation.id === activeConversationId
      : activeScreen === "workspace" && !activeConversationId && entry.item.imagery_id === activeImageryId

  const grouped = GROUP_LABELS.map(([group, label]) => ({
    group,
    label,
    items: entries.filter((entry) => groupForDate(entry.at) === group)
  }))

  return (
    <Sidebar collapsible="offcanvas" className="border-r border-sidebar-border select-none">
      {/* Header: Brand, New Chat, and Sidebar Close Action */}
      <SidebarHeader className="p-3 pb-2 border-b border-sidebar-border/30">
        <div className="flex items-center justify-between gap-2">
          <div 
            className="flex items-center gap-2 px-1 cursor-pointer hover:opacity-90 transition-opacity"
            onClick={() => {
              onNewChat()
              dismissSidebar()
            }}
            title="SatQuery AI - New Analysis"
          >
            <div className="w-7 h-7 rounded-full bg-white flex items-center justify-center p-0.5 border border-blue-500/40 shadow-sm shrink-0">
              <ChitravitsEmblem size={24} />
            </div>
            <span className="font-bold text-sm tracking-tight text-sidebar-foreground">
              Sat<span className="text-blue-500">Query</span> <span className="text-[10px] px-1 py-0.2 rounded bg-blue-500/20 text-blue-400 font-semibold border border-blue-500/30 ml-0.5">AI</span>
            </span>
          </div>

          <div className="flex items-center gap-0.5">
            <SidebarTrigger className="hover:bg-sidebar-accent rounded-lg p-1.5 transition-colors cursor-pointer text-sidebar-foreground" title="Close Sidebar (Ctrl+B)" />
          </div>
        </div>

        {/* Primary ChatGPT-Style Fast Shortcuts */}
        <SidebarMenu className="mt-2">
          <SidebarMenuItem>
            <SidebarMenuButton
              onClick={() => {
                onNewChat()
                dismissSidebar()
              }}
              tooltip="New Chat"
            >
              <SquarePen aria-hidden="true" />
              <span>New chat</span>
            </SidebarMenuButton>
          </SidebarMenuItem>

          <SidebarMenuItem>
            <SidebarMenuButton
              onClick={() => {
                onNavigateScreen("fusion")
                dismissSidebar()
              }}
              isActive={activeScreen === "fusion"}
              tooltip="Multimodal Satellite Images"
            >
              <ImageIcon aria-hidden="true" />
              <span>Images</span>
            </SidebarMenuButton>
          </SidebarMenuItem>

          <SidebarMenuItem>
            <SidebarMenuButton
              onClick={() => {
                onNavigateScreen("model-attach")
                dismissSidebar()
              }}
              isActive={activeScreen === "model-attach"}
              className="text-[0.92rem] py-2 h-9 relative"
              tooltip="Attach Custom AI Model (Folder Drag & Drop)"
            >
              <Cpu className="w-4 h-4 text-sidebar-foreground" />
              <span className="flex-1 truncate">Attach model</span>
              {activeModel && (
                <span 
                  className="w-2 h-2 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.85)] shrink-0" 
                  title={`Active Model: ${activeModel.name}`} 
                />
              )}
            </SidebarMenuButton>
          </SidebarMenuItem>

          <SidebarMenuItem>
            <SidebarMenuButton
              onClick={() => {
                onNavigateScreen("projects")
                dismissSidebar()
              }}
              isActive={activeScreen === "projects"}
              className="text-[0.92rem] py-2 h-9"
              tooltip="ChatGPT-Style Project Workspaces"
            >
              <FolderKanban className="w-4 h-4 text-sidebar-foreground" />
              <span>Projects</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      {/* Main Content: Chronological Chat History -- backend-driven only */}
      <SidebarContent className="px-2 scrollbar-thin">
        {status === "loading" && (
          <div className="px-3 py-4 text-xs text-sidebar-foreground/50">Loading history…</div>
        )}

        {status === "error" && (
          <div className="px-3 py-4 flex flex-col items-start gap-2 text-xs text-sidebar-foreground/70">
            <div className="flex items-center gap-1.5">
              <AlertCircle className="w-3.5 h-3.5 text-red-400" />
              <span>Unable to load conversation history.</span>
            </div>
            {errorDetail && (
              <p className="text-[11px] leading-snug text-sidebar-foreground/55 break-words">{errorDetail}</p>
            )}
            <button
              onClick={fetchHistory}
              className="flex items-center gap-1 text-blue-400 hover:text-blue-300 transition-colors"
            >
              <RefreshCw className="w-3 h-3" />
              <span>Retry</span>
            </button>
          </div>
        )}

        {/* ChatGPT-Style Dedicated Projects Section */}
        {projects && projects.length > 0 && (
          <SidebarGroup className="py-1">
            <div className="flex items-center justify-between px-2 py-1">
              <SidebarGroupLabel className="text-xs font-semibold text-sidebar-foreground/60 tracking-wider uppercase p-0">
                Projects
              </SidebarGroupLabel>
              <button 
                onClick={() => {
                  onNavigateScreen("projects");
                  dismissSidebar();
                }}
                className="p-1 rounded hover:bg-sidebar-accent text-sidebar-foreground/70 hover:text-sidebar-foreground transition-colors cursor-pointer"
                title="Manage or create projects"
              >
                <Plus className="w-3.5 h-3.5" />
              </button>
            </div>
            <SidebarGroupContent>
              <SidebarMenu>
                {projects.slice(0, 4).map((p) => {
                  const isProjActive = activeScreen === "projects" && activeProjectId === p.id;
                  return (
                    <SidebarMenuItem key={p.id}>
                      <SidebarMenuButton
                        onClick={() => {
                          onOpenProject ? onOpenProject(p) : onNavigateScreen("projects");
                          dismissSidebar();
                        }}
                        isActive={isProjActive}
                        className="text-[0.88rem] py-1.5 h-8 gap-2"
                        tooltip={p.name}
                      >
                        <span className="text-sm shrink-0">{p.icon || "📁"}</span>
                        <span className="truncate">{p.name}</span>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  );
                })}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        )}

        {status === "ready" && entries.length === 0 && (
          <div className="px-3 py-4 text-xs text-sidebar-foreground/50">No conversations yet.</div>
        )}

        {status === "ready" && grouped.map(({ group, label, items }) => {
          if (items.length === 0) return null
          return (
            <SidebarGroup key={group} className="py-1">
              <SidebarGroupLabel className="text-xs font-semibold text-sidebar-foreground/60 px-2 py-1 tracking-wider uppercase">
                {label}
              </SidebarGroupLabel>
              <SidebarGroupContent>
                <SidebarMenu>
                  {items.map((entry) => (
                    <ConversationRow
                      key={entry.key}
                      entry={entry}
                      isActive={isEntryActive(entry)}
                      isMenuOpen={openMenuKey === entry.key}
                      onOpenMenu={setOpenMenuKey}
                      onSelect={handleItemClick}
                      onRename={handleRename}
                      onDelete={handleDelete}
                    />
                  ))}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          )
        })}
      </SidebarContent>

      {/* Footer: User Profile */}
      <SidebarFooter className="p-3 border-t border-sidebar-border/60">
        <SidebarMenu className="gap-1">
          {/* User Profile Tile + its menu, which opens upward from it (anchored,
              not portaled): it stays inside the sidebar at any width/height.
              Spacing uses inline px / arbitrary px sizes on purpose: the global
              `* { margin: 0; padding: 0 }` reset in index.css is unlayered, so
              it overrides Tailwind's padding/margin utilities (p-*, m-*), and
              rem sizes follow a 15px root. */}
          <SidebarMenuItem>
            <div className="relative">
              <SidebarMenuButton
                ref={profileTriggerRef}
                data-state={isProfileMenuOpen ? "open" : "closed"}
                isActive={activeScreen === "profile"}
                aria-haspopup="menu"
                aria-expanded={isProfileMenuOpen}
                onClick={() => setIsProfileMenuOpen((open) => !open)}
                style={{ padding: "0 8px" }}
                className="h-[52px] w-full gap-[10px] rounded-lg"
              >
                <ProfileAvatar user={profileUser} className="h-[36px] w-[36px] text-[13px]" />
                <div className="flex min-w-0 flex-1 flex-col justify-center">
                  <span className="truncate text-[15px] font-semibold leading-5 text-sidebar-foreground">
                    {profileUser?.display_name ?? "Profile"}
                  </span>
                  {profileUser && (
                    <span className="truncate text-[12px] leading-4 text-sidebar-foreground/60">
                      {planLabel(profileUser.plan)}
                    </span>
                  )}
                </div>
                <span className="flex h-[32px] w-[32px] shrink-0 items-center justify-center rounded-md text-sidebar-foreground/60" aria-hidden="true">
                  <MoreHorizontal className="h-[16px] w-[16px]" />
                </span>
              </SidebarMenuButton>

              {isProfileMenuOpen && (
                // Spans the trigger minus 6px each side, 10px above it; never
                // leaves the sidebar. Fixed dark surface, as before.
                <div
                  ref={profileMenuRef}
                  role="menu"
                  aria-label="Account"
                  style={{ left: 6, right: 6, bottom: "calc(100% + 10px)", padding: 6 }}
                  className="absolute z-50 flex max-h-[calc(100svh-5rem)] flex-col overflow-y-auto rounded-[11px] border border-[rgba(59,130,246,0.18)] bg-[#080d18] shadow-[0_14px_32px_rgba(0,0,0,0.5),0_0_24px_rgba(59,130,246,0.06)] animate-in fade-in-0 slide-in-from-bottom-1 duration-150"
                >
                  <div className="flex items-center gap-[12px]" style={{ padding: "10px 8px" }}>
                    <ProfileAvatar user={profileUser} className="h-[36px] w-[36px] text-[13px]" />
                    <div className="flex min-w-0 flex-col">
                      <span className="truncate text-[15px] font-semibold leading-[20px] text-white">
                        {profileUser?.display_name ?? "Profile"}
                      </span>
                      {profileUser && (
                        <span className="truncate text-[12.5px] leading-[16px] text-[#8fa3bf]" style={{ marginTop: 2 }}>
                          @{profileUser.username}
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="h-px shrink-0 bg-[rgba(255,255,255,0.08)]" style={{ margin: "4px -6px" }} />

                  {[
                    {
                      label: "Profile",
                      icon: <User className="h-[16px] w-[16px] text-[#cbd5e1]" />,
                      onSelect: () => {
                        onOpenProfile?.()
                        dismissSidebar()
                      }
                    },
                    {
                      label: "Settings",
                      icon: <Settings className="h-[16px] w-[16px] text-[#cbd5e1]" />,
                      onSelect: () => {
                        onOpenSettings()
                        dismissSidebar()
                      }
                    },
                    {
                      label: "Upgrade Plan",
                      icon: <Sparkles className="h-[16px] w-[16px] text-blue-400" />,
                      onSelect: () => {
                        onNavigateScreen("report")
                        dismissSidebar()
                      }
                    }
                  ].map(({ label, icon, onSelect }) => (
                    <button
                      key={label}
                      role="menuitem"
                      style={{ padding: "0 8px" }}
                      className="flex h-[44px] w-full shrink-0 items-center gap-[11px] rounded-md text-left text-[14px] leading-[20px] text-[#e5e7eb] transition-colors duration-150 hover:bg-[rgba(255,255,255,0.04)] focus-visible:bg-[rgba(255,255,255,0.04)] focus-visible:outline-none"
                      onClick={() => {
                        setIsProfileMenuOpen(false)
                        onSelect()
                      }}
                    >
                      <span className="flex w-[20px] shrink-0 justify-center">{icon}</span>
                      <span>{label}</span>
                    </button>
                  ))}

                  <div className="h-px shrink-0 bg-[rgba(255,255,255,0.08)]" style={{ margin: "4px -6px" }} />

                  <button
                    role="menuitem"
                    style={{ padding: "0 8px" }}
                    className="flex h-[44px] w-full shrink-0 items-center gap-[11px] rounded-md text-left text-[14px] leading-[20px] text-[#ef4444] transition-colors duration-150 hover:bg-[rgba(239,68,68,0.08)] focus-visible:bg-[rgba(239,68,68,0.08)] focus-visible:outline-none"
                    onClick={() => setIsProfileMenuOpen(false)}
                  >
                    <span className="flex w-[20px] shrink-0 justify-center">
                      <LogOut className="h-[16px] w-[16px] text-[#ef4444]" />
                    </span>
                    <span>Sign Out</span>
                  </button>
                </div>
              )}
            </div>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
  )
}
