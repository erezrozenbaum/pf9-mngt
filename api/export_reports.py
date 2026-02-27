"""
Export helpers: generate Excel (.xlsx) and PDF reports from a migration plan dict.
Called by migration_routes.py export endpoints.
"""
from __future__ import annotations

import io
from datetime import datetime
from typing import Any, Dict, List

# ── Excel ────────────────────────────────────────────────────────────────────
import openpyxl
from openpyxl.styles import (
    Alignment, Border, Font, PatternFill, Side,
)
from openpyxl.utils import get_column_letter

# ── PDF ──────────────────────────────────────────────────────────────────────
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

# ══════════════════════════════════════════════════════════════════════════════
# Colour palette
# ══════════════════════════════════════════════════════════════════════════════
_BLUE    = "1D4ED8"  # header bg
_BLUE_LT = "DBEAFE"  # section header
_GREY    = "F3F4F6"  # alternating row
_GREEN   = "DCFCE7"
_RED     = "FEE2E2"
_YELLOW  = "FEF9C3"
_WHITE   = "FFFFFF"

def _thin_border():
    s = Side(border_style="thin", color="D1D5DB")
    return Border(left=s, right=s, top=s, bottom=s)


# ══════════════════════════════════════════════════════════════════════════════
# Excel report
# ══════════════════════════════════════════════════════════════════════════════

def generate_excel_report(plan: Dict[str, Any], project_name: str) -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # remove default sheet

    _sheet_summary(wb, plan, project_name)
    _sheet_per_tenant(wb, plan)
    _sheet_daily_schedule(wb, plan)
    _sheet_all_vms(wb, plan)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── helpers ──────────────────────────────────────────────────────────────────

def _hdr_font(wb):
    return Font(bold=True, color=_WHITE, name="Calibri", size=11)

def _hdr_fill():
    return PatternFill("solid", fgColor=_BLUE)

def _hdr_fill_lt():
    return PatternFill("solid", fgColor=_BLUE_LT)

def _grey_fill():
    return PatternFill("solid", fgColor=_GREY)

def _set_col_widths(ws, widths: List[float]):
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

def _write_table_header(ws, row: int, cols: List[str]):
    for ci, label in enumerate(cols, 1):
        c = ws.cell(row=row, column=ci, value=label)
        c.font = Font(bold=True, color=_WHITE, name="Calibri", size=9)
        c.fill = _hdr_fill()
        c.border = _thin_border()
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

def _write_row(ws, row: int, values: List[Any], alt: bool = False, fill_hex: str | None = None):
    fill = PatternFill("solid", fgColor=fill_hex) if fill_hex else (_grey_fill() if alt else PatternFill())
    for ci, val in enumerate(values, 1):
        c = ws.cell(row=row, column=ci, value=val)
        c.fill = fill
        c.border = _thin_border()
        c.font = Font(name="Calibri", size=9)
        c.alignment = Alignment(vertical="top", wrap_text=True)

# ── Sheet 1: Summary ──────────────────────────────────────────────────────────

def _sheet_summary(wb, plan: Dict, project_name: str):
    ws = wb.create_sheet("Summary")
    ws.sheet_view.showGridLines = False

    # Title row
    ws.merge_cells("A1:E1")
    t = ws["A1"]
    t.value = f"Migration Plan Report — {project_name}"
    t.font = Font(bold=True, name="Calibri", size=16, color=_BLUE)
    t.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 30

    ws.merge_cells("A2:E2")
    sub = ws["A2"]
    sub.value = f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
    sub.font = Font(name="Calibri", size=10, color="6B7280")

    ws.append([])  # blank row 3

    ps = plan.get("project_summary", {})
    bm = plan.get("bandwidth_model", {})

    kv_pairs = [
        ("Total VMs",            ps.get("total_vms", "")),
        ("Total Tenants",        ps.get("total_tenants", "")),
        ("Total Disk (TB)",      ps.get("total_disk_tb", "")),
        ("Warm Eligible",        ps.get("warm_eligible", "")),
        ("Cold Required",        ps.get("cold_required", "")),
        ("Warm Risky",           ps.get("warm_risky", "")),
        ("vJailbreak Agents",    ps.get("agent_count", "")),
        ("Concurrent Slots",     ps.get("total_concurrent_slots", "")),
        ("Schedule Days",        ps.get("estimated_schedule_days", "")),
        ("Project Duration",     f"{ps.get('project_duration_days', '')} days"),
        ("Working Hours/Day",    ps.get("working_hours_per_day", "")),
        ("Total Downtime (h)",   ps.get("total_downtime_hours", "")),
        ("Bottleneck",           bm.get("bottleneck", "")),
        ("Bottleneck (Mbps)",    ps.get("bottleneck_mbps", "")),
        ("Source NIC (Mbps)",    bm.get("source_effective_mbps", "")),
        ("Link (Mbps)",          bm.get("link_effective_mbps", "")),
        ("Agent Ingest (Mbps)",  bm.get("agent_effective_mbps", "")),
        ("Storage Write (Mbps)", bm.get("storage_effective_mbps", "")),
    ]

    ws.cell(row=4, column=1, value="Metric").font = Font(bold=True, name="Calibri", size=10)
    ws.cell(row=4, column=2, value="Value").font = Font(bold=True, name="Calibri", size=10)
    ws.cell(row=4, column=1).fill = _hdr_fill_lt()
    ws.cell(row=4, column=2).fill = _hdr_fill_lt()

    for i, (k, v) in enumerate(kv_pairs, 5):
        alt = (i % 2 == 0)
        ws.cell(row=i, column=1, value=k).fill = _grey_fill() if alt else PatternFill()
        ws.cell(row=i, column=2, value=v).fill = _grey_fill() if alt else PatternFill()
        for ci in (1, 2):
            ws.cell(row=i, column=ci).font = Font(name="Calibri", size=10)
            ws.cell(row=i, column=ci).border = _thin_border()

    _set_col_widths(ws, [28, 22, 10, 10, 10])


# ── Sheet 2: Per-Tenant Assessment ────────────────────────────────────────────

def _sheet_per_tenant(wb, plan: Dict):
    ws = wb.create_sheet("Per-Tenant Assessment")
    ws.sheet_view.showGridLines = False

    cols = [
        "Tenant", "OrgVDC", "VMs", "vCPU", "RAM (GB)",
        "Disk (GB)", "In Use (GB)", "Warm", "Warm Risky", "Cold",
        "Phase1 (h)", "Cutover (h)", "Downtime (h)", "Avg Risk Score",
    ]
    _write_table_header(ws, 1, cols)

    for i, tp in enumerate(plan.get("tenant_plans", []), 2):
        mode_fill = None
        if tp.get("cold_count", 0) > 0:
            mode_fill = _RED
        elif tp.get("warm_risky_count", 0) > 0:
            mode_fill = _YELLOW
        _write_row(ws, i, [
            tp.get("tenant_name", ""),
            tp.get("org_vdc", ""),
            tp.get("vm_count", 0),
            tp.get("total_vcpu", 0),
            round(tp.get("total_ram_mb", 0) / 1024, 1) if tp.get("total_ram_mb") else 0,
            round(float(tp.get("total_disk_gb", 0)), 1),
            round(float(tp.get("total_in_use_gb", 0)), 1),
            tp.get("warm_count", 0),
            tp.get("warm_risky_count", 0),
            tp.get("cold_count", 0),
            round(float(tp.get("total_warm_phase1_hours", 0)), 2),
            round(float(tp.get("total_warm_cutover_hours", 0)), 2),
            round(float(tp.get("total_downtime_hours", 0)), 2),
            round(float(tp.get("avg_risk_score", 0)), 1),
        ], alt=(i % 2 == 0), fill_hex=mode_fill)

    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}1"
    ws.freeze_panes = "A2"
    _set_col_widths(ws, [22, 16, 6, 6, 8, 9, 10, 7, 9, 6, 9, 9, 10, 11])


# ── Sheet 3: Daily Schedule ───────────────────────────────────────────────────

def _sheet_daily_schedule(wb, plan: Dict):
    ws = wb.create_sheet("Daily Schedule")
    ws.sheet_view.showGridLines = False

    cols = ["Day", "Tenant", "VM Name", "Mode", "OS Family", "Disk (GB)", "In Use (GB)", "Est. Hours"]
    _write_table_header(ws, 1, cols)

    row = 2
    for day in plan.get("daily_schedule", []):
        day_num = day.get("day", "")
        for vm in day.get("vms", []):
            mode = vm.get("mode", "")
            fill = _RED if mode == "cold_required" else (_YELLOW if mode == "warm_risky" else None)
            _write_row(ws, row, [
                day_num,
                vm.get("tenant_name", ""),
                vm.get("vm_name", ""),
                mode.replace("_", " "),
                vm.get("os_family", ""),
                round(float(vm.get("disk_gb", 0)), 1),
                round(float(vm.get("in_use_gb", 0)), 1),
                round(float(vm.get("est_hours", 0)), 2),
            ], alt=(row % 2 == 0), fill_hex=fill)
            row += 1
        # blank row between days
        row += 1

    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}1"
    ws.freeze_panes = "A2"
    _set_col_widths(ws, [6, 22, 30, 14, 12, 9, 10, 9])


# ── Sheet 4: All VMs ─────────────────────────────────────────────────────────

def _sheet_all_vms(wb, plan: Dict):
    ws = wb.create_sheet("All VMs")
    ws.sheet_view.showGridLines = False

    cols = [
        "VM Name", "Tenant", "OrgVDC", "vCPU", "CPU %", "RAM (MB)", "Mem %",
        "Disk (GB)", "In Use (GB)", "OS Family", "OS Version", "Power",
        "NICs", "Network", "IP", "Mode", "Risk", "Risk Score",
        "Phase1 (h)", "Cutover (h)", "Downtime (h)",
    ]
    _write_table_header(ws, 1, cols)

    row = 2
    for tp in plan.get("tenant_plans", []):
        for vm in tp.get("vms", []):
            mode = vm.get("migration_mode", "")
            risk = vm.get("risk_category", "")
            fill = _RED if mode == "cold_required" else (
                _YELLOW if mode == "warm_risky" else (
                    _RED if risk == "RED" else (_YELLOW if risk == "YELLOW" else None)
                )
            )
            _write_row(ws, row, [
                vm.get("vm_name", ""),
                tp.get("tenant_name", ""),
                tp.get("org_vdc", ""),
                vm.get("cpu_count", ""),
                vm.get("cpu_usage_percent", ""),
                vm.get("ram_mb", ""),
                vm.get("memory_usage_percent", ""),
                round(float(vm.get("total_disk_gb", 0) or 0), 1),
                round(float(vm.get("in_use_gb", 0) or 0), 1),
                vm.get("os_family", ""),
                vm.get("os_version", ""),
                vm.get("power_state", ""),
                vm.get("nic_count", ""),
                vm.get("network_name", ""),
                vm.get("primary_ip", ""),
                mode.replace("_", " "),
                risk,
                round(float(vm.get("risk_score", 0) or 0), 1),
                round(float(vm.get("warm_phase1_hours", 0) or 0), 2),
                round(float(vm.get("warm_cutover_hours", 0) or 0), 2),
                round(float(vm.get("warm_downtime_hours", 0) or 0), 2),
            ], alt=(row % 2 == 0), fill_hex=fill)
            row += 1

    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}1"
    ws.freeze_panes = "A2"
    _set_col_widths(ws, [28, 20, 16, 5, 6, 8, 6, 8, 9, 10, 22, 8, 4, 20, 14, 13, 6, 8, 9, 9, 10])


# ══════════════════════════════════════════════════════════════════════════════
# PDF report
# ══════════════════════════════════════════════════════════════════════════════

def generate_pdf_report(plan: Dict[str, Any], project_name: str) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=2.0 * cm,
        bottomMargin=1.5 * cm,
        title=f"Migration Plan — {project_name}",
    )

    styles = getSampleStyleSheet()
    s_title   = ParagraphStyle("Title2",   parent=styles["Title"],   fontSize=18, spaceAfter=4, textColor=colors.HexColor("#1D4ED8"))
    s_h2      = ParagraphStyle("H2",       parent=styles["Heading2"],fontSize=12, spaceAfter=4, textColor=colors.HexColor("#1E40AF"), spaceBefore=14)
    s_body    = ParagraphStyle("Body",     parent=styles["Normal"],  fontSize=9,  spaceAfter=4)
    s_caption = ParagraphStyle("Caption",  parent=styles["Normal"],  fontSize=8,  textColor=colors.grey, spaceAfter=8)
    s_footer  = ParagraphStyle("Footer",   parent=styles["Normal"],  fontSize=8,  textColor=colors.grey, alignment=TA_CENTER)

    _HDR  = colors.HexColor("#1D4ED8")
    _HDR_LT = colors.HexColor("#DBEAFE")
    _GREY_P = colors.HexColor("#F3F4F6")
    _RED_P  = colors.HexColor("#FEE2E2")
    _YEL_P  = colors.HexColor("#FEF9C3")
    _GRN_P  = colors.HexColor("#DCFCE7")
    _BLK    = colors.black

    story: list = []

    # ── Title ──────────────────────────────────────────────────────────────
    story.append(Paragraph(f"Migration Plan Report", s_title))
    story.append(Paragraph(f"<b>Project:</b> {project_name}", s_body))
    story.append(Paragraph(
        f"Generated: {datetime.utcnow().strftime('%B %d, %Y  %H:%M UTC')}",
        s_caption,
    ))
    story.append(HRFlowable(width="100%", thickness=1, color=_HDR, spaceAfter=10))

    # ── Project Summary ────────────────────────────────────────────────────
    story.append(Paragraph("Project Summary", s_h2))
    ps = plan.get("project_summary", {})
    bm = plan.get("bandwidth_model", {})

    summary_data = [
        ["Metric", "Value", "Metric", "Value"],
        ["Total VMs",            str(ps.get("total_vms", "—")),
         "vJailbreak Agents",    str(ps.get("agent_count", "—"))],
        ["Total Tenants",        str(ps.get("total_tenants", "—")),
         "Concurrent Slots",     str(ps.get("total_concurrent_slots", "—"))],
        ["Total Disk (TB)",      str(ps.get("total_disk_tb", "—")),
         "Schedule Days",        str(ps.get("estimated_schedule_days", "—"))],
        ["Warm Eligible",        str(ps.get("warm_eligible", "—")),
         "Project Duration",     f"{ps.get('project_duration_days', '—')} days"],
        ["Cold Required",        str(ps.get("cold_required", "—")),
         "Total Downtime (h)",   str(ps.get("total_downtime_hours", "—"))],
        ["Bottleneck",           str(bm.get("bottleneck", "—")).replace("_", " "),
         "Bottleneck (Mbps)",    str(ps.get("bottleneck_mbps", "—"))],
    ]
    t_sum = Table(summary_data, colWidths=[5.5*cm, 3.5*cm, 5.5*cm, 3.5*cm])
    t_sum.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _HDR),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 1), (-1, -1), _GREY_P),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _GREY_P]),
        ("FONTNAME",   (0, 1), (0, -1), "Helvetica-Bold"),
        ("FONTNAME",   (2, 1), (2, -1), "Helvetica-Bold"),
        ("GRID",       (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING",   (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
    ]))
    story.append(t_sum)
    story.append(Spacer(1, 0.4 * cm))

    # ── Per-Tenant Assessment ──────────────────────────────────────────────
    story.append(Paragraph("Per-Tenant Assessment", s_h2))

    tenant_header = [
        "Tenant", "OrgVDC", "VMs", "vCPU", "RAM (GB)",
        "Disk (GB)", "In Use\n(GB)", "Warm", "Cold", "Phase1 (h)", "Cutover (h)", "Avg Risk",
    ]
    tenant_rows = [tenant_header]
    for tp in plan.get("tenant_plans", []):
        has_cold = tp.get("cold_count", 0) > 0
        has_risky = tp.get("warm_risky_count", 0) > 0
        tenant_rows.append([
            tp.get("tenant_name", ""),
            tp.get("org_vdc", "") or "—",
            tp.get("vm_count", 0),
            tp.get("total_vcpu", 0),
            round(tp.get("total_ram_mb", 0) / 1024, 1) if tp.get("total_ram_mb") else 0,
            round(float(tp.get("total_disk_gb", 0)), 1),
            round(float(tp.get("total_in_use_gb", 0)), 1),
            tp.get("warm_count", 0),
            tp.get("cold_count", 0),
            round(float(tp.get("total_warm_phase1_hours", 0)), 1),
            round(float(tp.get("total_warm_cutover_hours", 0)), 1),
            round(float(tp.get("avg_risk_score", 0)), 1),
        ])

    cw_tenant = [4.5*cm, 3*cm, 1.5*cm, 1.5*cm, 2*cm, 2*cm, 2*cm, 1.5*cm, 1.5*cm, 2.5*cm, 2.5*cm, 2*cm]
    t_tenant = Table(tenant_rows, colWidths=cw_tenant, repeatRows=1)
    style_tenant = [
        ("BACKGROUND", (0, 0), (-1, 0), _HDR),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _GREY_P]),
        ("GRID",       (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN",      (2, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING",   (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
    ]
    # Highlight rows with cold VMs
    for ri, tp in enumerate(plan.get("tenant_plans", []), 1):
        if tp.get("cold_count", 0) > 0:
            style_tenant.append(("BACKGROUND", (0, ri), (-1, ri), _RED_P))
        elif tp.get("warm_risky_count", 0) > 0:
            style_tenant.append(("BACKGROUND", (0, ri), (-1, ri), _YEL_P))
    t_tenant.setStyle(TableStyle(style_tenant))
    story.append(t_tenant)
    story.append(Spacer(1, 0.4 * cm))

    # ── Daily Schedule ─────────────────────────────────────────────────────
    story.append(Paragraph("Daily Migration Schedule (Estimated)", s_h2))
    story.append(Paragraph(
        f"VMs ordered by tenant → priority → disk size. "
        f"Each day fills {ps.get('total_concurrent_slots', '?')} concurrent slots.",
        s_caption,
    ))

    sched_header = ["Day", "Tenant", "VM Name", "Mode", "OS Family", "Disk (GB)", "In Use (GB)", "Est. Hours"]
    sched_rows = [sched_header]
    for day in plan.get("daily_schedule", []):
        day_num = day.get("day", "")
        for vm in day.get("vms", []):
            sched_rows.append([
                f"Day {day_num}",
                vm.get("tenant_name", ""),
                vm.get("vm_name", ""),
                (vm.get("mode", "") or "").replace("_", " "),
                vm.get("os_family", ""),
                round(float(vm.get("disk_gb", 0)), 1),
                round(float(vm.get("in_use_gb", 0)), 1),
                round(float(vm.get("est_hours", 0)), 2),
            ])

    cw_sched = [1.8*cm, 4*cm, 7*cm, 3*cm, 2.5*cm, 2*cm, 2.5*cm, 2.5*cm]
    t_sched = Table(sched_rows, colWidths=cw_sched, repeatRows=1)
    style_sched = [
        ("BACKGROUND", (0, 0), (-1, 0), _HDR),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, -1), 7.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _GREY_P]),
        ("GRID",       (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
        ("VALIGN",     (0, 0), (-1, -1), "TOP"),
        ("ALIGN",      (5, 0), (-1, -1), "RIGHT"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING",   (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 2),
    ]
    for ri, row in enumerate(sched_rows[1:], 1):
        mode_str = row[3] if len(row) > 3 else ""
        if "cold" in mode_str:
            style_sched.append(("BACKGROUND", (0, ri), (-1, ri), _RED_P))
        elif "risky" in mode_str:
            style_sched.append(("BACKGROUND", (0, ri), (-1, ri), _YEL_P))
    t_sched.setStyle(TableStyle(style_sched))
    story.append(t_sched)
    story.append(Spacer(1, 0.4 * cm))

    # ── All VMs ────────────────────────────────────────────────────────────
    from reportlab.platypus import PageBreak
    story.append(PageBreak())
    story.append(Paragraph("All VMs — Full Inventory", s_h2))
    story.append(Paragraph(
        "Complete VM list with all key properties for migration planning.",
        s_caption,
    ))

    vm_all_header = [
        "VM Name", "Tenant", "vCPU", "RAM\n(MB)", "Disk\n(GB)", "In Use\n(GB)",
        "OS", "IP Address", "Network", "Power", "Mode", "Risk",
    ]
    vm_all_rows = [vm_all_header]
    for tp in plan.get("tenant_plans", []):
        for vm in tp.get("vms", []):
            mode = vm.get("migration_mode", "")
            risk = vm.get("risk_category", "")
            vm_all_rows.append([
                vm.get("vm_name", ""),
                tp.get("tenant_name", ""),
                vm.get("cpu_count", ""),
                vm.get("ram_mb", ""),
                round(float(vm.get("total_disk_gb", 0) or 0), 1),
                round(float(vm.get("in_use_gb", 0) or 0), 1),
                f"{vm.get('os_family','') or ''} {vm.get('os_version','') or ''}".strip() or "—",
                vm.get("primary_ip", "") or "—",
                vm.get("network_name", "") or "—",
                vm.get("power_state", "") or "—",
                (mode or "").replace("_", " "),
                risk or "—",
            ])

    cw_all = [6*cm, 3.5*cm, 1.3*cm, 1.8*cm, 1.8*cm, 1.8*cm, 3.3*cm, 3*cm, 4*cm, 2*cm, 2.8*cm, 1.7*cm]
    t_all = Table(vm_all_rows, colWidths=cw_all, repeatRows=1)
    style_all = [
        ("BACKGROUND", (0, 0), (-1, 0), _HDR),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, -1), 7),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _GREY_P]),
        ("GRID",       (0, 0), (-1, -1), 0.4, colors.HexColor("#D1D5DB")),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN",      (2, 0), (5, -1), "CENTER"),
        ("ALIGN",      (11, 0), (11, -1), "CENTER"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING",   (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 2),
    ]
    # Colour rows by mode/risk
    for ri, vm_row in enumerate(vm_all_rows[1:], 1):
        mode_str = vm_row[10] if len(vm_row) > 10 else ""
        risk_str = vm_row[11] if len(vm_row) > 11 else ""
        if "cold" in mode_str:
            style_all.append(("BACKGROUND", (0, ri), (-1, ri), _RED_P))
        elif "risky" in mode_str:
            style_all.append(("BACKGROUND", (0, ri), (-1, ri), _YEL_P))
        elif risk_str == "RED":
            style_all.append(("BACKGROUND", (11, ri), (11, ri), _RED_P))
        elif risk_str == "YELLOW":
            style_all.append(("BACKGROUND", (11, ri), (11, ri), _YEL_P))
        elif risk_str == "GREEN":
            style_all.append(("BACKGROUND", (11, ri), (11, ri), _GRN_P))
    t_all.setStyle(TableStyle(style_all))
    story.append(t_all)

    # ── Footer page numbers via onLaterPages ───────────────────────────────
    def _footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.grey)
        txt = f"Platform9 Migration Planner  ·  {project_name}  ·  Page {doc.page}"
        canvas.drawCentredString(landscape(A4)[0] / 2, 0.8 * cm, txt)
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()


# ══════════════════════════════════════════════════════════════════════════════
# Gap Analysis Action Report  (Excel + PDF)
# ══════════════════════════════════════════════════════════════════════════════

_EFFORT_MAP = {
    "missing_flavor":  "Medium — create matching PCD flavor",
    "missing_network": "High   — provision VLAN / network segment in PCD",
    "missing_image":   "Medium — upload/register OS image in Glance",
    "unmapped_tenant": "Low    — set Target Domain/Project in Tenant Scoping",
}

def _gap_effort(gap_type: str) -> str:
    for key, val in _EFFORT_MAP.items():
        if key in (gap_type or ""):
            return val
    return "Low — review and mark resolved"


def _gap_action_steps(gap: Dict[str, Any]) -> str:
    """Return a short set of recommended steps for a gap."""
    gt = (gap.get("gap_type") or "").lower()
    res = gap.get("resolution", "")
    details = gap.get("details") or {}
    if "flavor" in gt:
        vcpu = details.get("required_vcpu") or details.get("required vcpu", "?")
        ram  = details.get("required_ram") or details.get("ram", "?")
        return f"1. Open PCD → Admin → Flavors\n2. Create flavor: vCPU={vcpu}, RAM={ram} GB\n3. Mark gap Resolved"
    if "network" in gt:
        name = details.get("network_name") or gap.get("resource_name", "?")
        return f"1. Verify VLAN/segment '{name}' exists in your SDN\n2. Create Neutron network in PCD with matching name/VLAN\n3. Assign to relevant project(s)\n4. Mark gap Resolved"
    if "image" in gt:
        name = gap.get("resource_name", "?")
        return f"1. Download/prepare OS image for '{name}'\n2. Upload to Glance: openstack image create ...\n3. Set correct properties (disk_format, container_format)\n4. Mark gap Resolved"
    if "tenant" in gt or "unmapped" in gt:
        tenant = gap.get("tenant_name") or gap.get("resource_name", "?")
        return f"1. Open Migration Planner → Tenants → Target Mapping\n2. Set Target Domain + Project for '{tenant}'\n3. Mark gap Resolved"
    return res or "Review gap details and take corrective action, then mark Resolved."


# ── Excel ────────────────────────────────────────────────────────────────────

def generate_gaps_excel_report(
    gaps: List[Dict[str, Any]],
    project_name: str,
    readiness_score: float | None = None,
    quota_summary: Dict | None = None,
    sizing: Dict | None = None,
) -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    _gaps_sheet_summary(wb, gaps, project_name, readiness_score, quota_summary, sizing)
    _gaps_sheet_action_items(wb, gaps)
    _gaps_sheet_all_gaps(wb, gaps)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _gaps_sheet_summary(wb, gaps, project_name, score, quota, sizing):
    ws = wb.create_sheet("Executive Summary")
    _set_col_widths(ws, [28, 22, 22, 22])

    # Title
    ws.merge_cells("A1:D1")
    t = ws["A1"]; t.value = f"PCD Readiness Report — {project_name}"
    t.font = Font(bold=True, color=_WHITE, size=14, name="Calibri")
    t.fill = _hdr_fill(); t.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    ws.merge_cells("A2:D2")
    ts = ws["A2"]; ts.value = f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    ts.font = Font(size=9, color="6B7280", name="Calibri")
    ts.alignment = Alignment(horizontal="center")

    row = 4
    # Score
    ws.merge_cells(f"A{row}:B{row}")
    ws[f"A{row}"] = "Readiness Score"
    ws[f"A{row}"].font = Font(bold=True, size=11, name="Calibri")
    ws[f"C{row}"] = f"{score:.1f} / 100" if score is not None else "Not analysed"
    score_val = float(score or 0)
    score_fill = "DCFCE7" if score_val >= 80 else ("FFFBEB" if score_val >= 50 else "FEE2E2")
    ws[f"C{row}"].fill = PatternFill("solid", fgColor=score_fill)
    ws[f"C{row}"].font = Font(bold=True, size=14, name="Calibri")
    row += 2

    # Gap counts by severity
    criticals  = [g for g in gaps if g.get("severity") == "critical"  and not g.get("resolved")]
    warnings   = [g for g in gaps if g.get("severity") == "warning"   and not g.get("resolved")]
    infos      = [g for g in gaps if g.get("severity") == "info"      and not g.get("resolved")]
    resolved_n = sum(1 for g in gaps if g.get("resolved"))

    for label, val, fill in [
        ("Open Critical Gaps", len(criticals), _RED),
        ("Open Warning Gaps",  len(warnings),  _YELLOW[1:] if len(_YELLOW) == 6 else "FEF9C3"),
        ("Open Info Gaps",     len(infos),     _GREY),
        ("Resolved Gaps",      resolved_n,     _GREEN),
    ]:
        ws[f"A{row}"] = label
        ws[f"A{row}"].font = Font(bold=True, name="Calibri", size=10)
        ws[f"B{row}"] = val
        ws[f"B{row}"].fill = PatternFill("solid", fgColor=fill)
        ws[f"B{row}"].font = Font(bold=True, size=12, name="Calibri")
        ws[f"B{row}"].alignment = Alignment(horizontal="center")
        row += 1

    row += 1
    # Gap type breakdown
    ws[f"A{row}"] = "Gap Type Breakdown"
    ws[f"A{row}"].font = Font(bold=True, size=11, name="Calibri", color=_WHITE)
    ws[f"A{row}"].fill = _hdr_fill()
    ws[f"B{row}"] = "Open"
    ws[f"B{row}"].font = Font(bold=True, size=11, name="Calibri", color=_WHITE)
    ws[f"B{row}"].fill = _hdr_fill()
    ws[f"B{row}"].alignment = Alignment(horizontal="center")
    row += 1
    from collections import Counter
    type_counts = Counter(g.get("gap_type", "unknown") for g in gaps if not g.get("resolved"))
    for gtype, cnt in sorted(type_counts.items(), key=lambda x: -x[1]):
        ws[f"A{row}"] = gtype.replace("_", " ").title()
        ws[f"B{row}"] = cnt
        ws[f"B{row}"].alignment = Alignment(horizontal="center")
        row += 1

    if quota and (quota.get("vcpu") or quota.get("ram_gb")):
        row += 1
        ws[f"A{row}"] = "Migration Quota Requirements"
        ws[f"A{row}"].font = Font(bold=True, size=11, name="Calibri", color=_WHITE)
        ws.merge_cells(f"A{row}:D{row}")
        ws[f"A{row}"].fill = _hdr_fill()
        row += 1
        for label, val in [
            ("vCPU Required", quota.get("vcpu", "—")),
            ("RAM Required (GB)", quota.get("ram_gb", "—")),
            ("Disk Required (TB)", quota.get("disk_tb", "—")),
        ]:
            ws[f"A{row}"] = label
            ws[f"B{row}"] = val
            row += 1


def _gaps_sheet_action_items(wb, gaps):
    ws = wb.create_sheet("Action Items (Unresolved)")
    _set_col_widths(ws, [22, 20, 16, 12, 12, 35, 28])
    cols = ["Gap Type", "Resource", "Tenant", "Severity", "Effort", "Action Steps", "Resolution"]
    _write_table_header(ws, 1, cols)
    ws.freeze_panes = "A2"

    unresolved = [g for g in gaps if not g.get("resolved")]
    unresolved.sort(key=lambda g: (0 if g.get("severity") == "critical" else 1
                                    if g.get("severity") == "warning" else 2))

    sev_fills = {"critical": _RED, "warning": "FEF9C3", "info": _GREY}
    for i, g in enumerate(unresolved, 1):
        sev  = g.get("severity", "info")
        fill = sev_fills.get(sev, _GREY)
        _write_row(ws, i + 1, [
            (g.get("gap_type") or "").replace("_", " ").title(),
            g.get("resource_name", ""),
            g.get("tenant_name") or "—",
            sev,
            _gap_effort(g.get("gap_type", "")),
            _gap_action_steps(g),
            g.get("resolution", ""),
        ], fill_hex=fill if sev == "critical" else None, alt=(i % 2 == 0))
        ws.row_dimensions[i + 1].height = 48
    ws.auto_filter.ref = f"A1:G{len(unresolved) + 1}"


def _gaps_sheet_all_gaps(wb, gaps):
    ws = wb.create_sheet("All Gaps")
    _set_col_widths(ws, [22, 20, 16, 12, 10, 35])
    cols = ["Gap Type", "Resource", "Tenant", "Severity", "Status", "Resolution"]
    _write_table_header(ws, 1, cols)
    ws.freeze_panes = "A2"
    for i, g in enumerate(gaps, 1):
        status = "✓ Resolved" if g.get("resolved") else "Open"
        _write_row(ws, i + 1, [
            (g.get("gap_type") or "").replace("_", " ").title(),
            g.get("resource_name", ""),
            g.get("tenant_name") or "—",
            g.get("severity", "info"),
            status,
            g.get("resolution", ""),
        ], alt=(i % 2 == 0))
    ws.auto_filter.ref = f"A1:F{len(gaps) + 1}"


# ── PDF ──────────────────────────────────────────────────────────────────────

def generate_gaps_pdf_report(
    gaps: List[Dict[str, Any]],
    project_name: str,
    readiness_score: float | None = None,
    quota_summary: Dict | None = None,
    sizing: Dict | None = None,
) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                            leftMargin=1.5*cm, rightMargin=1.5*cm,
                            topMargin=1.5*cm, bottomMargin=1.8*cm)

    styles = getSampleStyleSheet()
    _HDR  = colors.HexColor("#1D4ED8")
    _GREY_P = colors.HexColor("#F3F4F6")
    _RED_P  = colors.HexColor("#FEE2E2")
    _YEL_P  = colors.HexColor("#FEF9C3")

    def _h1(text):
        return Paragraph(f"<font color='#1D4ED8'><b>{text}</b></font>",
                         ParagraphStyle("h1", parent=styles["Heading1"], fontSize=14,
                                        spaceAfter=6, textColor=colors.HexColor(_HDR.hexval() if hasattr(_HDR, 'hexval') else "#1D4ED8")))

    def _h2(text):
        return Paragraph(f"<b>{text}</b>",
                         ParagraphStyle("h2", parent=styles["Heading2"], fontSize=11, spaceAfter=4))

    def _body(text):
        return Paragraph(text, ParagraphStyle("body", parent=styles["Normal"], fontSize=8, leading=11))

    story = []

    # Title
    story.append(Paragraph(
        f"<font size='16' color='#1D4ED8'><b>PCD Readiness Action Report</b></font>",
        ParagraphStyle("title", parent=styles["Title"], alignment=TA_CENTER, spaceAfter=4)
    ))
    story.append(Paragraph(
        f"Project: <b>{project_name}</b>  ·  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        ParagraphStyle("sub", parent=styles["Normal"], alignment=TA_CENTER, fontSize=9,
                       textColor=colors.HexColor("#6B7280"), spaceAfter=12)
    ))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#E5E7EB")))
    story.append(Spacer(1, 0.3*cm))

    # Score summary row
    score_val = float(readiness_score or 0)
    score_color_hex = "#16a34a" if score_val >= 80 else ("#d97706" if score_val >= 50 else "#dc2626")
    criticals  = sum(1 for g in gaps if g.get("severity") == "critical"  and not g.get("resolved"))
    warnings   = sum(1 for g in gaps if g.get("severity") == "warning"   and not g.get("resolved"))
    resolved_n = sum(1 for g in gaps if g.get("resolved"))

    summary_data = [
        ["Readiness Score", "Critical Gaps", "Warning Gaps", "Resolved"],
        [
            f"{score_val:.1f} / 100" if readiness_score is not None else "N/A",
            str(criticals), str(warnings), str(resolved_n),
        ]
    ]
    t_sum = Table(summary_data, colWidths=[7*cm, 5*cm, 5*cm, 5*cm])
    t_sum.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _HDR),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONTSIZE",   (0, 0), (-1, -1), 10),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN",      (0, 0), (-1, -1), "CENTER"),
        ("BACKGROUND", (1, 1), (1, 1), colors.HexColor("#FEE2E2") if criticals else colors.HexColor("#DCFCE7")),
        ("BACKGROUND", (2, 1), (2, 1), colors.HexColor("#FEF9C3") if warnings else colors.HexColor("#DCFCE7")),
        ("BACKGROUND", (3, 1), (3, 1), colors.HexColor("#DCFCE7")),
        ("GRID",       (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t_sum)
    story.append(Spacer(1, 0.5*cm))

    # Action Items table (unresolved only)
    story.append(_h2("Action Items — Unresolved Gaps"))
    story.append(Spacer(1, 0.15*cm))

    unresolved = [g for g in gaps if not g.get("resolved")]
    unresolved.sort(key=lambda g: (0 if g.get("severity") == "critical" else
                                    1 if g.get("severity") == "warning" else 2))

    if not unresolved:
        story.append(_body("✅ No unresolved gaps. All gaps have been marked resolved."))
    else:
        ai_header = [["#", "Gap Type", "Resource / Tenant", "Sev.", "Action Steps"]]
        ai_rows = []
        for idx, g in enumerate(unresolved, 1):
            sev = g.get("severity", "info")
            ai_rows.append([
                str(idx),
                Paragraph((g.get("gap_type") or "").replace("_", " ").title(),
                           ParagraphStyle("s", fontSize=7, leading=9)),
                Paragraph(f"{g.get('resource_name', '')}\\n"
                           f"<font color='#6B7280'>{g.get('tenant_name') or ''}</font>",
                           ParagraphStyle("s", fontSize=7, leading=9)),
                Paragraph(f"<font color='{'#dc2626' if sev=='critical' else '#d97706' if sev=='warning' else '#374151'}'><b>{sev}</b></font>",
                           ParagraphStyle("s", fontSize=7, leading=9)),
                Paragraph(_gap_action_steps(g).replace("\n", "<br/>"),
                           ParagraphStyle("s", fontSize=7, leading=9)),
            ])
        ai_data = ai_header + ai_rows
        cw = [0.8*cm, 4*cm, 5*cm, 1.8*cm, 16*cm]
        t_ai = Table(ai_data, colWidths=cw, repeatRows=1)
        ai_style = [
            ("BACKGROUND", (0, 0), (-1, 0), _HDR),
            ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
            ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",   (0, 0), (-1, 0), 8),
            ("GRID",       (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
            ("VALIGN",     (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING",    (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
        for i, g in enumerate(unresolved, 1):
            sev = g.get("severity", "info")
            if sev == "critical":
                ai_style.append(("BACKGROUND", (0, i), (3, i), colors.HexColor("#FEE2E2")))
            elif sev == "warning":
                ai_style.append(("BACKGROUND", (0, i), (3, i), colors.HexColor("#FEF9C3")))
            elif i % 2 == 0:
                ai_style.append(("ROWBACKGROUNDS", (0, i), (-1, i), [_GREY_P]))
        t_ai.setStyle(TableStyle(ai_style))
        story.append(t_ai)

    story.append(Spacer(1, 0.5*cm))

    # All Gaps summary table
    story.append(_h2(f"All Gaps ({len(gaps)} total, {resolved_n} resolved)"))
    story.append(Spacer(1, 0.15*cm))

    if not gaps:
        story.append(_body("No gaps recorded. Run 'Run Gap Analysis' in the PCD Readiness tab."))
    else:
        all_header = [["Gap Type", "Resource", "Tenant", "Severity", "Status", "Resolution"]]
        all_rows = [[
            Paragraph((g.get("gap_type") or "").replace("_", " ").title(),
                       ParagraphStyle("s", fontSize=7)),
            Paragraph(g.get("resource_name", ""), ParagraphStyle("s", fontSize=7)),
            Paragraph(g.get("tenant_name") or "—", ParagraphStyle("s", fontSize=7)),
            Paragraph(g.get("severity", ""), ParagraphStyle("s", fontSize=7)),
            Paragraph("✓ Resolved" if g.get("resolved") else "Open", ParagraphStyle("s", fontSize=7)),
            Paragraph(g.get("resolution", ""), ParagraphStyle("s", fontSize=7, leading=9)),
        ] for g in gaps]
        all_data = all_header + all_rows
        cw2 = [4*cm, 4.5*cm, 4.5*cm, 2.3*cm, 2.3*cm, 9.4*cm]
        t_all = Table(all_data, colWidths=cw2, repeatRows=1)
        t_all.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), _HDR),
            ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
            ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",   (0, 0), (-1, 0), 8),
            ("GRID",       (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _GREY_P]),
            ("VALIGN",     (0, 0), (-1, -1), "TOP"),
            ("FONTSIZE",   (0, 1), (-1, -1), 7),
            ("TOPPADDING",    (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        story.append(t_all)

    def _footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.grey)
        txt = (f"Platform9 Migration Planner  ·  PCD Readiness  ·  {project_name}"
               f"  ·  Page {doc.page}")
        canvas.drawCentredString(landscape(A4)[0] / 2, 0.8*cm, txt)
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
