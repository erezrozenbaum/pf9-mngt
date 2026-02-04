# UI Component Integration Quick Start

## Files Added

✅ **React Components:**
- `pf9-ui/src/components/SnapshotPolicyManager.tsx` - Main snapshot management dashboard
- `pf9-ui/src/components/SnapshotAuditTrail.tsx` - Audit trail viewer with filtering

✅ **Stylesheets:**
- `pf9-ui/src/styles/SnapshotPolicyManager.css` - Dashboard styling
- `pf9-ui/src/styles/SnapshotAuditTrail.css` - Audit trail styling

✅ **Documentation:**
- `docs/SNAPSHOT_UI_COMPONENTS.md` - Complete component reference

## Integration Steps (3 minutes)

### Step 1: Add Imports to App.tsx

Open `pf9-ui/src/App.tsx` and add after existing component imports:

```typescript
import SnapshotPolicyManager from "./components/SnapshotPolicyManager";
import SnapshotAuditTrail from "./components/SnapshotAuditTrail";
```

### Step 2: Add Navigation Tabs

Find the tab buttons section (around line 2110) and add:

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

### Step 3: Add Tab Content

Find the tab content section and add:

```typescript
{activeTab === "snapshot-policies" && (
  <SnapshotPolicyManager />
)}

{activeTab === "snapshot-audit" && (
  <SnapshotAuditTrail />
)}
```

### Step 4: Update Type Definition

Update the `activeTab` state type to include new tabs:

```typescript
type ActiveTab = "servers" | "snapshots" | "networks" | "subnets" | "volumes" 
  | "domains" | "tenants" | "projects" | "hypervisors" | "flavors" | "images" 
  | "users" | "roles" | "management" | "snapshot-policies" | "snapshot-audit";
```

## How to Test

1. **Run UI dev server:**
   ```bash
   cd pf9-ui
   npm run dev
   ```

2. **Open browser to http://localhost:5173**

3. **Login with credentials**

4. **Click new tabs:**
   - "📸 Snapshot Policies" → View/manage policies
   - "📋 Snapshot Audit" → View audit trail

## Features at a Glance

### Snapshot Policies Tab
- ✅ Create new snapshot policies
- ✅ Edit existing policies
- ✅ Delete policies with confirmation
- ✅ View volume assignments
- ✅ Track execution runs and history

### Snapshot Audit Tab
- ✅ Search snapshot operations
- ✅ Filter by tenant, project, action
- ✅ View detailed error messages
- ✅ Paginate through thousands of records
- ✅ Export audit trail to CSV

## API Endpoints Required

These endpoints must be running (from Step 2):

```
✅ GET  /api/snapshot/policy-sets
✅ POST /api/snapshot/policy-sets
✅ PATCH /api/snapshot/policy-sets/{id}
✅ DELETE /api/snapshot/policy-sets/{id}

✅ GET /api/snapshot/assignments
✅ DELETE /api/snapshot/assignments/{volume_id}

✅ GET /api/snapshot/runs

✅ GET /api/snapshot/records
```

## Permissions

UI respects role-based access:

| Role | Can View | Can Create | Can Delete |
|------|----------|-----------|-----------|
| Viewer | ✅ | ❌ | ❌ |
| Operator | ✅ | ✅ | ✅ |
| Admin | ✅ | ✅ | ✅ |
| Superadmin | ✅ | ✅ | ✅ |

## Next Steps

After integration:

1. **Test the UI** - Create a test policy, verify it appears
2. **Run snapshots** - p9_auto_snapshots.py logs to DB
3. **View audit trail** - See operations tracked in UI
4. **Export reports** - Download CSV for compliance

## Troubleshooting

### "API is not accessible"
- Verify API running: `docker ps | grep pf9_api`
- Check CORS: `curl -i http://localhost:8000/api/snapshot/policy-sets`

### "No data showing"
- Verify policies created: Check DB with `psql`
- Check browser console for JS errors
- Verify authentication token in localStorage

### "Permission denied"
- Verify user role: Admin or above required for creation
- Check role_permissions table: `SELECT * FROM role_permissions WHERE resource='snapshot';`

## Complete Example

See `docs/SNAPSHOT_UI_COMPONENTS.md` for comprehensive documentation including:
- Full TypeScript types
- Component prop details
- CSS custom properties
- Testing strategies
- Performance optimization
- Future enhancement roadmap

---

**Status:** ✅ Ready to Integrate
**Time to Integrate:** ~5 minutes
**Dependencies:** React 18+, Node 16+, running API server
