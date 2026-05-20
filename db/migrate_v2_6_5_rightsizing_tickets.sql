-- =============================================================================
-- migrate_v2_6_5_rightsizing_tickets.sql
--
-- Enables the tenant "Request Resize" flow to automatically open a support
-- ticket in the admin UI, and notifies the assigned department by email.
--
-- Changes:
--   1. departments.notification_email  — per-dept email for system notifications
--   2. ticket_email_templates          — "rightsizing_request" template (dept-facing)
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. Add notification_email to departments (optional, admin configures it)
-- ---------------------------------------------------------------------------
ALTER TABLE departments
    ADD COLUMN IF NOT EXISTS notification_email TEXT;

-- ---------------------------------------------------------------------------
-- 2. Add rightsizing_request email template
--    Sent to the department's notification_email when a tenant requests resize.
--    Uses the same {{key}} substitution as all other ticket templates.
-- ---------------------------------------------------------------------------
INSERT INTO ticket_email_templates (template_name, subject, html_body)
VALUES (
    'rightsizing_request',
    '[{{ticket_ref}}] Right-Sizing Request - {{vm_name}} ({{project_name}})',
    $$<div style="font-family:sans-serif;font-size:14px;color:#111;max-width:600px">
  <h2 style="color:#1a73e8;margin-bottom:4px">Right-Sizing Request</h2>
  <p style="color:#6b7280;margin-top:0">Ticket <strong>{{ticket_ref}}</strong> &middot; Priority: <strong>{{priority}}</strong></p>
  <p>A tenant has requested an infrastructure resize via the Cloud Portal.<br>
  Please review and schedule the change at your earliest convenience.</p>
  <table cellpadding="8" cellspacing="0" border="0" style="border-collapse:collapse;width:100%;font-size:14px">
    <tr style="background:#f9fafb"><td style="color:#6b7280;width:40%">VM</td><td><strong>{{vm_name}}</strong></td></tr>
    <tr><td style="color:#6b7280">Project</td><td>{{project_name}}</td></tr>
    <tr style="background:#f9fafb"><td style="color:#6b7280">Region</td><td>{{region}}</td></tr>
    <tr><td style="color:#6b7280">Current Flavor</td><td>{{current_flavor}} ({{current_vcpus}} vCPU / {{current_ram_gb}} GB RAM)</td></tr>
    <tr style="background:#f9fafb"><td style="color:#6b7280">Recommended Flavor</td><td style="color:#16a34a"><strong>{{recommended_flavor}}</strong> ({{recommended_vcpus}} vCPU / {{recommended_ram_gb}} GB RAM)</td></tr>
    <tr><td style="color:#6b7280">CPU / RAM Utilisation</td><td>CPU {{cpu_p95}}% / RAM {{ram_p95}}% (95th percentile, 7-day)</td></tr>
    <tr style="background:#f9fafb"><td style="color:#6b7280">Estimated Monthly Saving</td><td style="color:#16a34a;font-weight:bold">{{savings}}</td></tr>
    <tr><td style="color:#6b7280">Requested by Tenant</td><td>{{tenant_name}} ({{tenant_email}})</td></tr>
  </table>
  <hr style="margin:24px 0;border:none;border-top:1px solid #e5e7eb">
  <h3 style="color:#111;font-size:15px">Action Items</h3>
  <ol style="padding-left:20px;line-height:1.8">
    <li>Review the recommendation and utilisation data above.</li>
    <li>Contact the tenant to agree on a maintenance window.</li>
    <li>Execute the resize in OpenStack (openstack server resize).</li>
    <li>Mark this ticket as <strong>Resolved</strong> in the admin portal.</li>
    <li>The tenant will receive an automatic notification on resolution.</li>
  </ol>
  <p style="color:#6b7280;font-size:12px;margin-top:24px">
    This ticket was auto-created by pf9-mngt v{{app_version}}.
    View it under <em>Operations &amp; Support &rarr; Tickets</em>.
  </p>
</div>$$
)
ON CONFLICT (template_name) DO UPDATE
    SET subject   = EXCLUDED.subject,
        html_body = EXCLUDED.html_body,
        updated_at = now();
