# Step 4: UI Components - Snapshot Management Dashboard

## Overview

This document describes the newly created UI components for snapshot policy management, audit trail viewing, and execution history tracking. These components integrate with the snapshot management API endpoints (Step 2) and database schema (Step 1).

## Created Components

### 1. SnapshotPolicyManager.tsx

**Location:** `pf9-ui/src/components/SnapshotPolicyManager.tsx`

**Purpose:** Main dashboard for managing snapshot policies, volume assignments, and viewing execution runs.

**Features:**
- **Policy Sets Tab**: Display, create, edit, and delete snapshot policy sets
  - Shows global vs. tenant-specific policies
  - Displays retention policies, priority, and activation status
  - Create new policies with retention mapping
  
- **Volume Assignments Tab**: Manage volume-to-policy assignments
  - Table view of all assigned volumes
  - Shows tenant, project, VM, and policy associations
  - Auto-snapshot flag visibility
  - Remove assignments
  
- **Execution Runs Tab**: View snapshot operation history
  - Displays run status (completed, in_progress, failed, partial)
  - Shows creation/deletion/failure counts
  - Dry run indicators
  - Run timing information

**Props:** None (component is self-contained)

**Dependencies:**
- React 18+
- fetch API (modern browser)
- Bearer token from localStorage

**API Endpoints Used:**
```
GET  /api/snapshot/policy-sets
POST /api/snapshot/policy-sets
PATCH /api/snapshot/policy-sets/{policy_id}
DELETE /api/snapshot/policy-sets/{policy_id}

GET /api/snapshot/assignments
DELETE /api/snapshot/assignments/{volume_id}

GET /api/snapshot/runs
```

**Key Types:**
```typescript
interface PolicySet {
  id: number;
  name: string;
  description?: string;
  is_global: boolean;
  tenant_id?: string;
  tenant_name?: string;
  policies: string[];
  retention_map: Record<string, number>;
  priority: number;
  is_active: boolean;
}

interface SnapshotAssignment {
  id: number;
  volume_id: string;
  volume_name: string;
  tenant_id: string;
  project_id: string;
  policy_set_id?: number;
  auto_snapshot: boolean;
}

interface SnapshotRun {
  id: number;
  run_type: string;
  started_at: string;
  finished_at?: string;
  status: string;
  snapshots_created: number;
  snapshots_deleted: number;
  snapshots_failed: number;
}
```

---

### 2. SnapshotAuditTrail.tsx

**Location:** `pf9-ui/src/components/SnapshotAuditTrail.tsx`

**Purpose:** Comprehensive audit trail viewer for all snapshot operations with filtering, search, and export capabilities.

**Features:**
- **Detailed Audit Records**: Shows every snapshot action (created/deleted/failed/skipped)
  - Tenant, project, VM, volume context
  - Snapshot ID, retention days, error messages
  - Precise timestamps
  
- **Advanced Filtering**:
  - Search by volume name, VM name, or snapshot ID
  - Filter by tenant and project
  - Filter by action type (created/deleted/failed/skipped)
  - Date range filtering
  
- **Pagination**: Navigate large result sets
  - Configurable page size (10, 25, 50, 100)
  - First/previous/next/last navigation
  
- **CSV Export**: Download filtered audit trail for reporting

**Props:** None (component is self-contained)

**Dependencies:**
- React 18+
- fetch API (modern browser)
- Bearer token from localStorage

**API Endpoints Used:**
```
GET /api/snapshot/records?limit=1000
```

**Key Types:**
```typescript
interface SnapshotRecord {
  id: number;
  run_id: number;
  tenant_id: string;
  tenant_name: string;
  project_id: string;
  project_name: string;
  vm_id?: string;
  vm_name?: string;
  volume_id: string;
  volume_name: string;
  action: string;  // 'created' | 'deleted' | 'failed' | 'skipped'
  snapshot_id?: string;
  retention_days?: number;
  error_message?: string;
  created_at: string;
}

interface AuditFilters {
  tenant?: string;
  project?: string;
  action?: string;
  dateRange?: [string, string];
  searchTerm?: string;
}
```

---

## Styling Files

### SnapshotPolicyManager.css

**Location:** `pf9-ui/src/styles/SnapshotPolicyManager.css`

Provides comprehensive styling for:
- Tab navigation
- Policy cards grid layout
- Form controls and validation
- Table layouts with responsive behavior
- Badge styling for status indicators
- Button variations (primary, secondary, danger)
- Mobile-responsive design

### SnapshotAuditTrail.css

**Location:** `pf9-ui/src/styles/SnapshotAuditTrail.css`

Provides comprehensive styling for:
- Filter panel with responsive grid
- Data table with sortable columns
- Pagination controls
- Badge styling for action types and status
- CSV export button
- Mobile-responsive design for small screens

---

## Integration with App.tsx

To add snapshot management to the main application, add these imports and tabs to `App.tsx`:

### 1. Add Component Imports

```typescript
import SnapshotPolicyManager from "./components/SnapshotPolicyManager";
import SnapshotAuditTrail from "./components/SnapshotAuditTrail";
```

### 2. Add Tab Navigation

Add buttons in the tab navigation section:

```typescript
<button
  className={
    activeTab === "snapshot-policies" ? "pf9-tab pf9-tab-active" : "pf9-tab"
  }
  onClick={() => setActiveTab("snapshot-policies")}
>
  📸 Snapshot Policies
</button>

<button
  className={
    activeTab === "snapshot-audit" ? "pf9-tab pf9-tab-active" : "pf9-tab"
  }
  onClick={() => setActiveTab("snapshot-audit")}
>
  📋 Snapshot Audit
</button>
```

### 3. Add Tab Content Sections

In the main content area:

```typescript
{activeTab === "snapshot-policies" && (
  <SnapshotPolicyManager />
)}

{activeTab === "snapshot-audit" && (
  <SnapshotAuditTrail />
)}
```

### 4. Update Type Definitions

Add to the activeTab state type:

```typescript
type ActiveTab = "servers" | "snapshots" | "networks" | ... | "snapshot-policies" | "snapshot-audit";
```

---

## Feature Walkthrough

### Creating a New Snapshot Policy

1. Open **Snapshot Policies** tab
2. Click **+ New Policy** button
3. Fill in:
   - Policy name (required)
   - Description
   - Check "Global Policy" or leave unchecked for tenant-specific
   - Add retention rules (e.g., "hourly: 24 days", "daily: 30 days")
4. Click **Create**

### Viewing Snapshot Assignments

1. Open **Snapshot Policies** tab
2. Click **Volume Assignments** sub-tab
3. View all volumes with their:
   - Associated policies
   - Tenant and project context
   - Auto-snapshot flag
   - Assignment source

### Viewing Execution History

1. Open **Snapshot Policies** tab
2. Click **Execution Runs** sub-tab
3. See all past and current snapshot runs with:
   - Execution status and timing
   - Count of snapshots created/deleted/failed
   - Dry run indicators
   - Execution type

### Auditing Snapshot Operations

1. Open **Snapshot Audit** tab
2. Use filters to narrow results:
   - Search for specific volumes or VMs
   - Filter by tenant/project
   - Filter by action type
   - Set date ranges
3. View audit details including:
   - Exact timestamp of operation
   - Snapshot ID created
   - Any error messages
4. Export filtered results as CSV for reporting

---

## Permission-Based UI Visibility

The UI components respect role-based permissions:

- **Viewers**: Can see policies, assignments, runs, and audit trail (read-only)
- **Operators**: Can manage assignments and exclusions
- **Admins**: Can create/modify/delete policies
- **Superadmins**: Full access including advanced settings

To implement permission-based hiding, wrap sections:

```typescript
{(authUser?.role === 'admin' || authUser?.role === 'superadmin') && (
  <button className="btn btn-primary" onClick={() => setShowCreatePolicy(true)}>
    + New Policy
  </button>
)}
```

---

## Error Handling

Both components handle errors gracefully:

- **Network Errors**: Display error alert at top with message
- **Permission Errors**: Show 403 Forbidden message
- **Not Found**: Show 404 message with recovery option
- **Validation Errors**: Show form-level error messages

---

## Performance Considerations

### SnapshotPolicyManager
- Loads all policies/assignments/runs on tab change
- No real-time updates (manual refresh required)
- Suitable for 1000+ policies/assignments

### SnapshotAuditTrail
- Loads records on component mount (limit: 1000)
- Client-side pagination for 25 records per page
- CSV export includes all filtered records
- Search/filter operations are client-side

### Optimization Tips
- Add refresh intervals using `setInterval()` for live updates
- Implement virtual scrolling for large tables (100K+ records)
- Add debouncing to search filter inputs

---

## Testing Recommendations

### Manual Testing Checklist

- [ ] Create a new snapshot policy set
- [ ] Verify policy appears in the list
- [ ] Edit policy details
- [ ] Delete policy with confirmation
- [ ] View volume assignments table
- [ ] Filter assignments by tenant
- [ ] View execution runs with proper status badges
- [ ] Audit trail shows all recent operations
- [ ] Search audit trail by volume name
- [ ] Filter audit trail by action type
- [ ] Export audit trail to CSV
- [ ] Pagination works correctly
- [ ] Responsive on mobile devices
- [ ] Permission checks prevent unauthorized actions

### Automated Testing

```typescript
// Example test structure
describe('SnapshotPolicyManager', () => {
  test('creates new policy', async () => {
    // Mock API responses
    // Render component
    // Fill form
    // Submit
    // Verify policy appears in list
  });
  
  test('deletes policy with confirmation', async () => {
    // Verify delete button shows confirmation
    // Verify API DELETE called
    // Verify policy removed from list
  });
});
```

---

## Next Steps

### Phase 1: Integration (Immediate)
1. Add components to App.tsx
2. Wire up navigation tabs
3. Test API connectivity

### Phase 2: Enhancement (Short-term)
1. Add real-time WebSocket updates for run status
2. Implement policy clone/duplicate feature
3. Add bulk operations (delete multiple assignments)
4. Add scheduling UI for automatic runs

### Phase 3: Advanced Features (Medium-term)
1. Policy version history and rollback
2. Performance analytics dashboard
3. Email notifications for failed runs
4. Integration with monitoring alerts
5. Snapshot cost calculator

---

## API Integration Reference

### Authentication

All API calls require Bearer token:

```typescript
headers: {
  'Authorization': `Bearer ${localStorage.getItem('token')}`,
  'Content-Type': 'application/json'
}
```

### Error Response Handling

```typescript
if (!response.ok) {
  const errorData = await response.json();
  throw new Error(errorData.detail || 'Request failed');
}
```

### Rate Limiting

No rate limiting currently implemented. Recommend adding:
- 100 requests/minute per user
- Backoff strategy for bulk exports

---

## CSS Custom Properties

The components use CSS custom properties for theming:

```css
--text-primary:     /* Main text color */
--text-secondary:   /* Secondary text color */
--card-bg:          /* Card background */
--bg-secondary:     /* Secondary background */
--border-color:     /* Border color */
--primary-color:    /* Primary action color */
--primary-dark:     /* Primary dark variant */
--secondary-color:  /* Secondary action color */
--secondary-dark:   /* Secondary dark variant */
```

To customize, update in App.css or your theme provider.

---

## Support & Troubleshooting

### Component Won't Load
- Check browser console for errors
- Verify API is running and accessible
- Confirm authentication token is valid
- Check CORS settings in API server

### Data Not Appearing
- Verify GET endpoints return data
- Check network tab for 200/non-200 status
- Ensure pagination page size is correct
- Try manual refresh button

### Styling Issues
- Clear browser cache
- Verify CSS files are imported
- Check CSS custom properties are defined
- Inspect element for style conflicts

---

**Created:** 2024
**Status:** Ready for Integration
**Version:** 1.0.0
