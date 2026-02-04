# Snapshot UI Components - Testing Guide

## Overview

This guide provides comprehensive testing procedures for the snapshot management UI components before integration into App.tsx.

**Estimated Time:** 20-30 minutes
**Prerequisites:** API running, Database populated, Node.js 16+

---

## Pre-Integration Testing Checklist

### Phase 1: Environment Verification (5 minutes)

- [ ] **API Server Running**
  ```bash
  curl http://localhost:8000/api/snapshot/policy-sets
  # Expected: {"policy_sets": [...]} (may be empty)
  ```

- [ ] **Database Tables Exist**
  ```bash
  docker exec pf9_db psql -U postgres pf9_db -c "\dt snapshot_*"
  # Expected: 5 tables listed (policy_sets, assignments, exclusions, runs, records)
  ```

- [ ] **Authentication Token Available**
  ```bash
  # In browser console after login:
  console.log(localStorage.getItem('token'))
  # Expected: JWT token string
  ```

- [ ] **Component Files Present**
  ```bash
  ls -la pf9-ui/src/components/Snapshot*.tsx
  # Expected: 2 files listed
  ```

### Phase 2: TypeScript Validation (5 minutes)

```bash
cd pf9-ui

# Check TypeScript compilation
npm run build

# Expected output:
# ✓ built in 15.23s
```

**If errors occur:**
```bash
# Run type check only
npx tsc --noEmit

# Fix issues as reported
```

### Phase 3: Component Import Verification (5 minutes)

Create a test file to verify imports work:

**File:** `pf9-ui/src/test-imports.tsx`

```typescript
// Test imports
import SnapshotPolicyManager from './components/SnapshotPolicyManager';
import SnapshotAuditTrail from './components/SnapshotAuditTrail';

console.log('✓ SnapshotPolicyManager imported:', SnapshotPolicyManager);
console.log('✓ SnapshotAuditTrail imported:', SnapshotAuditTrail);

// Verify they're valid React components
if (typeof SnapshotPolicyManager === 'function') {
  console.log('✓ SnapshotPolicyManager is a valid React component');
}

if (typeof SnapshotAuditTrail === 'function') {
  console.log('✓ SnapshotAuditTrail is a valid React component');
}
```

Then run:
```bash
npx ts-node src/test-imports.tsx
```

### Phase 4: Development Server Test (5 minutes)

Start the development server and verify components load:

```bash
cd pf9-ui
npm run dev
```

**In Browser:**
1. Open http://localhost:5173
2. Open Developer Console (F12)
3. Look for errors - should see none related to Snapshot components
4. Check console output for any warnings

---

## Manual Testing Procedures

### Test 1: Policy Manager Component Loading

**Objective:** Verify SnapshotPolicyManager renders without errors

**Steps:**

1. Create a minimal test page:

```typescript
// pf9-ui/src/test-SnapshotPolicyManager.tsx
import React from 'react';
import SnapshotPolicyManager from './components/SnapshotPolicyManager';

export function TestPolicyManager() {
  // Mock token for testing
  localStorage.setItem('token', 'test-jwt-token-here');
  
  return (
    <div>
      <h1>Snapshot Policy Manager Test</h1>
      <SnapshotPolicyManager />
    </div>
  );
}

export default TestPolicyManager;
```

2. Update App.tsx temporarily to render this test:

```typescript
import TestPolicyManager from './test-SnapshotPolicyManager';

// In your render:
<TestPolicyManager />
```

3. Start dev server: `npm run dev`

4. Check browser console for errors

**Expected Results:**
- ✓ Component renders without errors
- ✓ Tabs visible (Policy Sets, Assignments, Runs)
- ✓ Loading state shows initially
- ✓ Data loads from API
- ✓ No TypeScript errors

**If errors occur:**
- Check browser console for specific error messages
- Verify API is running and accessible
- Verify auth token is valid
- Check that snapshot tables exist in database

---

### Test 2: Audit Trail Component Loading

**Objective:** Verify SnapshotAuditTrail renders and filters work

**Steps:**

1. Create a minimal test page:

```typescript
// pf9-ui/src/test-SnapshotAuditTrail.tsx
import React from 'react';
import SnapshotAuditTrail from './components/SnapshotAuditTrail';

export function TestAuditTrail() {
  localStorage.setItem('token', 'test-jwt-token-here');
  
  return (
    <div>
      <h1>Snapshot Audit Trail Test</h1>
      <SnapshotAuditTrail />
    </div>
  );
}

export default TestAuditTrail;
```

2. Render in App temporarily

3. Start dev server

4. Verify in browser:
   - [ ] Filters panel visible
   - [ ] Table renders
   - [ ] Search input works
   - [ ] Tenant dropdown populates
   - [ ] Pagination controls visible

---

### Test 3: API Connectivity

**Objective:** Verify components can reach API endpoints

**Browser Console Test:**

```javascript
// Test policy sets endpoint
fetch('http://localhost:8000/api/snapshot/policy-sets', {
  headers: {
    'Authorization': `Bearer ${localStorage.getItem('token')}`
  }
})
.then(r => r.json())
.then(d => console.log('✓ Policies loaded:', d.policy_sets.length))
.catch(e => console.error('✗ Error:', e.message));

// Test assignments endpoint
fetch('http://localhost:8000/api/snapshot/assignments', {
  headers: {
    'Authorization': `Bearer ${localStorage.getItem('token')}`
  }
})
.then(r => r.json())
.then(d => console.log('✓ Assignments loaded:', d.assignments.length))
.catch(e => console.error('✗ Error:', e.message));

// Test records endpoint
fetch('http://localhost:8000/api/snapshot/records?limit=100', {
  headers: {
    'Authorization': `Bearer ${localStorage.getItem('token')}`
  }
})
.then(r => r.json())
.then(d => console.log('✓ Records loaded:', d.records.length))
.catch(e => console.error('✗ Error:', e.message));
```

**Expected Results:**
- ✓ All three endpoints return 200 status
- ✓ Data arrays visible (may be empty initially)
- ✓ No CORS or authentication errors

---

### Test 4: User Interactions

**Objective:** Verify UI interactions work correctly

#### 4.1 Policy Manager - Create Policy

1. Navigate to Policy Sets tab
2. Click "+ New Policy" button
3. Verify form appears
4. Fill form:
   - Name: "Test Policy"
   - Description: "Test"
   - Check "Global Policy"
5. Click "Create"
6. Verify:
   - [ ] Form closes
   - [ ] Policy appears in list
   - [ ] No console errors
   - [ ] API was called (check Network tab)

#### 4.2 Policy Manager - View Assignments

1. Click "Volume Assignments" tab
2. Verify table loads with columns:
   - Volume, Tenant, Project, VM, Policies, Auto Snapshot, Source, Actions
3. If data exists:
   - [ ] Rows display correctly
   - [ ] All columns populated
   - [ ] Badge styling applied

#### 4.3 Audit Trail - Search

1. Navigate to Audit Trail tab
2. In search input, type "volume" (or any text)
3. Verify:
   - [ ] Table filters in real-time
   - [ ] Results update
   - [ ] No errors in console

#### 4.4 Audit Trail - Filter

1. Select tenant from dropdown
2. Verify:
   - [ ] Table filters by tenant
   - [ ] Record count updates
3. Select action type filter
4. Verify:
   - [ ] Combined filtering works
   - [ ] Multiple filters work together

#### 4.5 Audit Trail - Pagination

1. Click page size selector (25, 50, 100)
2. Verify:
   - [ ] Table updates
   - [ ] Correct number of rows shown
3. Click "Next" button
4. Verify:
   - [ ] Page changes
   - [ ] New data displayed
   - [ ] Page indicator updates

#### 4.6 Audit Trail - Export

1. Click "Export CSV" button
2. Verify:
   - [ ] CSV file downloads
   - [ ] Filename is `snapshot-audit-trail-YYYY-MM-DD.csv`
   - [ ] File contains data with headers

---

### Test 5: Permission Checks

**Objective:** Verify role-based access control works

**For Viewer Role:**
- [ ] Can see all policies
- [ ] Cannot click "Create" button (or button disabled)
- [ ] Can view audit trail
- [ ] Can export CSV

**For Operator Role:**
- [ ] Can create assignments
- [ ] Can delete assignments
- [ ] Can view policies
- [ ] Cannot create/edit policies

**For Admin Role:**
- [ ] Can create policies
- [ ] Can edit policies
- [ ] Can delete policies
- [ ] Full access to all features

---

### Test 6: Responsive Design

**Objective:** Verify UI works on different screen sizes

**Desktop (1920x1080):**
- [ ] All elements visible
- [ ] Tables display with all columns
- [ ] No horizontal scroll
- [ ] Spacing looks good

**Tablet (768x1024):**
- [ ] Layout adapts
- [ ] Tables may have scroll
- [ ] Touch targets are adequate
- [ ] No overlapping elements

**Mobile (375x667):**
- [ ] Single column layout
- [ ] All controls visible
- [ ] Forms readable
- [ ] Buttons clickable

**In Browser DevTools:**
```javascript
// Set mobile dimensions
// Then reload and verify components adjust
```

---

### Test 7: Error Handling

**Objective:** Verify graceful error handling

#### 7.1 API Unavailable

1. Stop API: `docker-compose stop pf9_api`
2. Reload page
3. Verify in components:
   - [ ] Error message shown
   - [ ] Not a blank/crashed page
   - [ ] User can see what went wrong

#### 7.2 Invalid Token

1. Clear localStorage: `localStorage.clear()`
2. Reload page
3. Verify:
   - [ ] 401 Unauthorized error shown
   - [ ] Redirect to login (or shows error)
   - [ ] No sensitive data exposed

#### 7.3 Network Error

1. Open DevTools Network tab
2. Check "Offline"
3. Reload and try to create/filter
4. Verify:
   - [ ] Error message shown
   - [ ] No unhandled exceptions
   - [ ] UI recovers when back online

---

### Test 8: Browser Console Check

**Objective:** Ensure no warnings or errors

**Steps:**

1. Open browser DevTools Console (F12)
2. Reload page
3. Go through all tabs and features
4. Check for:
   - [ ] No error messages (red)
   - [ ] No type errors
   - [ ] No security warnings (except optional CORS in dev)

**Common issues to watch for:**
- `Cannot read property 'X' of undefined` → Check API response structure
- `useEffect infinite loop` → Check dependencies array
- `localStorage not defined` → Check if running in browser context
- `Failed to fetch` → Check API is running and CORS enabled

---

## Automated Testing Setup

### Unit Tests Example

Create file: `pf9-ui/src/components/__tests__/SnapshotPolicyManager.test.tsx`

```typescript
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import SnapshotPolicyManager from '../SnapshotPolicyManager';

// Mock fetch
global.fetch = jest.fn();

describe('SnapshotPolicyManager', () => {
  beforeEach(() => {
    localStorage.setItem('token', 'test-token');
    (fetch as jest.Mock).mockClear();
  });

  test('renders policy manager component', async () => {
    (fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ policy_sets: [] })
    });

    render(<SnapshotPolicyManager />);
    
    await waitFor(() => {
      expect(screen.getByText('Policy Sets')).toBeInTheDocument();
    });
  });

  test('calls API on tab change', async () => {
    (fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({ policy_sets: [], assignments: [], runs: [] })
    });

    render(<SnapshotPolicyManager />);
    
    const assignmentsTab = screen.getByText('Volume Assignments');
    fireEvent.click(assignmentsTab);

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining('/snapshot/assignments'),
        expect.any(Object)
      );
    });
  });
});
```

Run tests with:
```bash
npm run test
```

---

## Test Results Documentation

### Testing Checklist Summary

| Test Area | Status | Notes |
|-----------|--------|-------|
| TypeScript Compilation | ⚪ | Not started |
| Component File Verification | ⚪ | Not started |
| API Connectivity | ⚪ | Not started |
| Policy Manager Rendering | ⚪ | Not started |
| Audit Trail Rendering | ⚪ | Not started |
| Create Policy | ⚪ | Not started |
| View Assignments | ⚪ | Not started |
| Search/Filter | ⚪ | Not started |
| Pagination | ⚪ | Not started |
| Export CSV | ⚪ | Not started |
| Permission Checks | ⚪ | Not started |
| Responsive Design | ⚪ | Not started |
| Error Handling | ⚪ | Not started |
| Console Errors | ⚪ | Not started |

**Legend:** ⚪ Not started | 🟡 In progress | 🟢 Passed | 🔴 Failed

---

## Quick Test Commands

```bash
# Check TypeScript
cd pf9-ui && npm run build

# Run lint
npm run lint

# Type check only
npx tsc --noEmit

# Start dev server
npm run dev

# Run tests (if configured)
npm run test

# Check for unused imports
npx tsc --noUnusedLocals --noUnusedParameters

# Build for production
npm run build
```

---

## Troubleshooting

### Issue: "Cannot find module"

**Solution:**
```bash
# Verify file paths are correct
ls -la pf9-ui/src/components/SnapshotPolicyManager.tsx

# Rebuild node_modules
rm -rf pf9-ui/node_modules
npm install
```

### Issue: "localStorage is not defined"

**Solution:**
- Ensure running in browser environment
- Check token is set before component loads
- Verify in browser console

### Issue: "API returns 401"

**Solution:**
```bash
# Check token is valid
# Relogin to get new token
# Verify token in localStorage
```

### Issue: "Component not rendering data"

**Solution:**
```javascript
// Debug in console
const token = localStorage.getItem('token');
fetch('http://localhost:8000/api/snapshot/policy-sets', {
  headers: { 'Authorization': `Bearer ${token}` }
})
.then(r => r.json())
.then(console.log)
```

---

## Test Sign-Off

Once all tests pass, sign off:

```
Date: ________________
Tester: ________________
Status: ✓ PASSED / ✗ FAILED
Notes: _________________________________________________

All 14 test areas verified and working correctly.
Ready to proceed with UI integration into App.tsx.
```

---

## Next Steps After Testing

If all tests pass:
1. ✅ Proceed with App.tsx integration (UI_INTEGRATION_GUIDE.md)
2. ✅ Clean up test files
3. ✅ Commit changes
4. ✅ Deploy to production

If tests fail:
1. ❌ Document failure details
2. ❌ Fix identified issues
3. ❌ Re-run failed tests
4. ❌ Update this document
5. ❌ Retry from failed step

---

**Testing Estimated Duration:** 20-30 minutes
**Difficulty Level:** Beginner to Intermediate
**Success Criteria:** All tests pass without errors
