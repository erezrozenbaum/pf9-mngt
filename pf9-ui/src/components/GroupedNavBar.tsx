import React, { useRef, useState } from "react";
import type { NavGroupDef } from "../hooks/useNavigation";

/**
 * Two-level navigation bar with drag-and-drop reordering:
 *  - Top row: nav group pills (draggable to reorder)
 *  - Bottom row: tab items within the active group — only shown when
 *    a group pill is clicked. The "default" group (is_default=true)
 *    is always expanded on login.
 *
 * Clicking the same group pill again collapses (hides) the second row
 * UNLESS it's the default group.
 */

interface GroupedNavBarProps {
  groups: NavGroupDef[];
  activeGroupKey: string | null;
  activeTabKey: string | null;
  /** Whether to show the second layer (items row) */
  expandedGroupKey: string | null;
  onGroupChange: (groupKey: string) => void;
  onTabChange: (tabKey: string) => void;
  onToggleExpand: (groupKey: string) => void;
  onGroupReorder?: (fromKey: string, toKey: string) => void;
  onItemReorder?: (groupKey: string, fromKey: string, toKey: string) => void;
  onResetOrder?: () => void;
}

const GroupedNavBar: React.FC<GroupedNavBarProps> = ({
  groups,
  activeGroupKey,
  activeTabKey,
  expandedGroupKey,
  onGroupChange,
  onTabChange,
  onToggleExpand,
  onGroupReorder,
  onItemReorder,
  onResetOrder,
}) => {
  const expandedGroup = groups.find((g) => g.key === expandedGroupKey) ?? null;

  // Helper: is a nav item an "action" item? Uses the is_action flag from the database.
  const isActionItem = (item: any): boolean => !!item.is_action;

  // Helper: does a group contain at least one action item?
  const isActionGroup = (g: NavGroupDef): boolean => {
    return g.items.some((item: any) => isActionItem(item));
  };

  // Drag state for groups
  const dragGroupRef = useRef<string | null>(null);
  const dragOverGroupRef = useRef<string | null>(null);
  const [draggingGroup, setDraggingGroup] = useState<string | null>(null);

  // Drag state for items
  const dragItemRef = useRef<string | null>(null);
  const dragOverItemRef = useRef<string | null>(null);
  const [draggingItem, setDraggingItem] = useState<string | null>(null);

  // ── Group drag handlers ──
  const handleGroupDragStart = (key: string) => {
    dragGroupRef.current = key;
    setDraggingGroup(key);
  };
  const handleGroupDragOver = (e: React.DragEvent, key: string) => {
    e.preventDefault();
    dragOverGroupRef.current = key;
  };
  const handleGroupDrop = () => {
    const from = dragGroupRef.current;
    const to = dragOverGroupRef.current;
    if (from && to && from !== to && onGroupReorder) {
      onGroupReorder(from, to);
    }
    dragGroupRef.current = null;
    dragOverGroupRef.current = null;
    setDraggingGroup(null);
  };
  const handleGroupDragEnd = () => {
    setDraggingGroup(null);
  };

  // ── Item drag handlers ──
  const handleItemDragStart = (key: string) => {
    dragItemRef.current = key;
    setDraggingItem(key);
  };
  const handleItemDragOver = (e: React.DragEvent, key: string) => {
    e.preventDefault();
    dragOverItemRef.current = key;
  };
  const handleItemDrop = () => {
    const from = dragItemRef.current;
    const to = dragOverItemRef.current;
    if (from && to && from !== to && expandedGroupKey && onItemReorder) {
      onItemReorder(expandedGroupKey, from, to);
    }
    dragItemRef.current = null;
    dragOverItemRef.current = null;
    setDraggingItem(null);
  };
  const handleItemDragEnd = () => {
    setDraggingItem(null);
  };

  return (
    <div className="pf9-grouped-nav">
      {/* ── Group pills (top row) ── */}
      <div className="pf9-nav-groups">
        {groups.map((g) => (
          <button
            key={g.key}
            className={[
              "pf9-nav-group-pill",
              activeGroupKey === g.key ? "pf9-nav-group-active" : "",
              expandedGroupKey === g.key ? "pf9-nav-group-expanded" : "",
              isActionGroup(g) ? "pf9-nav-group-action" : "",
              draggingGroup === g.key ? "pf9-nav-dragging" : "",
            ]
              .filter(Boolean)
              .join(" ")}
            onClick={() => {
              // Toggle expand/collapse
              onToggleExpand(g.key);
              // Set as active group
              onGroupChange(g.key);
              // Auto-select first item in group if current tab not in it
              const itemKeys = g.items.map((i: any) => i.key);
              if (activeTabKey && !itemKeys.includes(activeTabKey) && g.items.length > 0) {
                onTabChange(g.items[0].key);
              }
            }}
            draggable
            onDragStart={() => handleGroupDragStart(g.key)}
            onDragOver={(e) => handleGroupDragOver(e, g.key)}
            onDrop={handleGroupDrop}
            onDragEnd={handleGroupDragEnd}
            title={g.is_default ? "Default group (always opens on login) · Drag to reorder" : "Click to expand · Drag to reorder"}
          >
            {g.icon ? <span className="pf9-nav-group-icon">{g.icon}</span> : null}
            {g.label}
            {g.is_default && <span className="pf9-nav-default-badge">★</span>}
          </button>
        ))}
        {onResetOrder && (
          <button
            className="pf9-nav-group-pill pf9-nav-reset-btn"
            onClick={onResetOrder}
            title="Reset navigation order to default"
          >
            ↩
          </button>
        )}
      </div>

      {/* ── Tab items (bottom row) — only shown when a group is expanded ── */}
      {expandedGroup && expandedGroup.items.length > 0 && (
        <div className="pf9-nav-items">
          {expandedGroup.items.map((item: any) => (
            <button
              key={item.key}
              className={[
                "pf9-tab",
                activeTabKey === item.key ? "pf9-tab-active" : "",
                isActionItem(item) ? "pf9-tab-action" : "",
                draggingItem === item.key ? "pf9-nav-dragging" : "",
              ]
                .filter(Boolean)
                .join(" ")}
              onClick={() => onTabChange(item.key)}
              draggable
              onDragStart={() => handleItemDragStart(item.key)}
              onDragOver={(e) => handleItemDragOver(e, item.key)}
              onDrop={handleItemDrop}
              onDragEnd={handleItemDragEnd}
              title="Drag to reorder tabs"
            >
              {item.icon ? <span style={{ marginRight: 4 }}>{item.icon}</span> : null}
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

export default GroupedNavBar;
