from datetime import date, timedelta
from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from .calculations import weekly_summary
from reportlab.graphics.shapes import Drawing, String, Rect, Line, Circle


def calorie_chart(report):
    drawing = Drawing(510, 190)
    days = report['days']
    ceiling = max([d[k] or 0 for d in days for k in ('intake_kcal', 'tdee_kcal')] + [1000]) * 1.15
    for i in range(5):
        y = 30 + i * 32
        drawing.add(Line(42, y, 505, y, strokeColor=colors.HexColor('#DEE6E7')))
        drawing.add(String(36, y-3, f'{ceiling*i/4:,.0f}', textAnchor='end', fontSize=8))
    for n, day in enumerate(days):
        x = 56 + n * 64
        for k, offset, color in [('intake_kcal', 0, '#F2A65A'), ('tdee_kcal', 21, '#267B83')]:
            value = day[k]
            if value is not None:
                drawing.add(Rect(x+offset, 30, 18, 128*value/ceiling, fillColor=colors.HexColor(color), strokeColor=None))
        drawing.add(String(x+19, 16, day['date'][5:], fontSize=8, textAnchor='middle'))
    drawing.add(Rect(160, 177, 9, 9, fillColor=colors.HexColor('#F2A65A'), strokeColor=None))
    drawing.add(String(174, 177, 'Food intake', fontSize=9))
    drawing.add(Rect(285, 177, 9, 9, fillColor=colors.HexColor('#267B83'), strokeColor=None))
    drawing.add(String(299, 177, 'Estimated TDEE', fontSize=9))
    return drawing


def deficit_chart(report):
    drawing = Drawing(510, 130)
    values = []
    running = 0
    for d in report['days']:
        if d['deficit_kcal'] is not None:
            running += d['deficit_kcal']
        values.append(running)
    low, high = min([0] + values), max([1] + values)
    def y(value):
        return 30 + 70*(value-low)/(high-low)
    drawing.add(Line(42, y(0), 500, y(0), strokeColor=colors.HexColor('#B5C9CC')))
    for n, value in enumerate(values):
        x = 61 + n * 69
        if n:
            drawing.add(Line(x-69, y(values[n-1]), x, y(value), strokeColor=colors.HexColor('#267B83'), strokeWidth=2))
        complete = report['days'][n]['complete']
        drawing.add(Circle(x, y(value), 3, fillColor=colors.HexColor('#267B83') if complete else colors.white,
                           strokeColor=colors.HexColor('#267B83')))
        drawing.add(String(x, y(value)+9, f'{value:,.0f}', textAnchor='middle', fontSize=8))
        drawing.add(String(x, 13, report['days'][n]['date'][5:], textAnchor='middle', fontSize=8))
    return drawing



def get_week(store, start, baseline):
    end = start + timedelta(days=6)
    result = weekly_summary(start, store.rows('food_logs', start, end),
                          store.rows('activity_logs', start, end),
                          store.rows('daily_summaries', start, end), baseline)
    from .config import profile_for
    result['profile'] = profile_for(end)
    return result


def pdf_bytes(report, timezone='Asia/Kathmandu', sample=False):
    out = BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4, rightMargin=36, leftMargin=36, topMargin=40, bottomMargin=40,
                            title='Weekly diet and fitness report', author='DietMCP', invariant=1)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='Muted', parent=styles['BodyText'], textColor=colors.HexColor('#566576'), leading=15))
    story = [Paragraph('DIET / WEEKLY REVIEW', styles['Title']),
             Paragraph(f"{report['start']} to {report['end']} | {timezone}", styles['Muted']), Spacer(1, 16)]
    if sample:
        story += [Paragraph('SAMPLE DATA - not your personal results', styles['Heading2']), Spacer(1, 8)]
    if report.get('profile'):
        p = report['profile']
        story += [Paragraph(f"Profile inputs: age {p['age']} | {p['height_cm']:.1f} cm | {p['weight_kg']:.1f} kg | "
                            f"User-stated target {p['target_weight_kg']:.1f} kg", styles['Muted']),
                  Paragraph(f"Estimated resting burn: {p['resting_kcal']:,.0f} kcal/day | "
                            f"Baseline before extra exercise: {p['baseline_kcal']:,.0f} kcal/day", styles['Muted']), Spacer(1, 8)]
    full = report['weekly_deficit_kcal']
    loss = report['estimated_weight_loss_kg']
    fmt = lambda x: '-' if x is None else f'{x:,.0f}'
    story += [Paragraph(f"Complete days: {report['complete_days']} / 7", styles['Heading2']),
              Paragraph(f"Total weekly deficit: {fmt(full)} kcal", styles['BodyText']),
              Paragraph(f"Complete-day deficit subtotal: {fmt(report['logged_days_deficit_kcal'])} kcal", styles['BodyText']),
              Paragraph('Estimated weekly weight-loss equivalent: ' + ('unavailable (incomplete week)' if loss is None else f'{loss:+.2f} kg'), styles['BodyText']), Spacer(1, 16)]
    story += [Paragraph('Daily calories: intake vs estimated TDEE', styles['Heading2']),
              calorie_chart(report), Spacer(1, 12),
              Paragraph('Cumulative deficit across complete days', styles['Heading2']),
              deficit_chart(report), Spacer(1, 12),
              Paragraph('Blank bars indicate missing values. The cumulative chart includes confirmed complete days only; '
                        'it is not a full-week estimate when days are incomplete.', styles['Muted']),
              PageBreak(), Paragraph('DAILY DETAIL', styles['Title']),
              Paragraph(f"{report['start']} to {report['end']} | All energy in kcal", styles['Muted']), Spacer(1, 16)]
    rows = [['Date', 'Intake\nkcal', 'Protein\ng', 'Exercise*\nkcal', 'TDEE*\nkcal', 'Deficit*\nkcal', 'Status']]
    for day in report['days']:
        rows.append([day['date'][5:], fmt(day['intake_kcal']), fmt(day['protein_g']), fmt(day['exercise_kcal']),
                     fmt(day['tdee_kcal']), fmt(day['deficit_kcal']), 'Complete' if day['complete'] else 'Partial'])
    table = Table(rows, colWidths=[55, 66, 58, 76, 70, 72, 64], repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#183D4B')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white), ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'), ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (1, 1), (-2, -1), 'RIGHT'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 10), ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#EDF3F4'), colors.white]),
        ('LINEBELOW', (0, -1), (-1, -1), 0.5, colors.HexColor('#CBD7DA'))]))
    story += [table, Spacer(1, 18), Paragraph('How to read this report', styles['Heading2']),
              Paragraph('* Estimates. Exercise is additional net burn beyond the configured baseline. '
                        'Step totals and workouts must not overlap. TDEE = baseline + exercise; deficit = TDEE - intake. '
                        'Positive deficit indicates an energy shortfall; negative indicates a surplus.', styles['Muted']), Spacer(1, 8),
              Paragraph('A dash means unknown. Partial days never contribute to claimed weekly totals or weight loss. '
                        'Confirm both food and activity logs to complete a day. A complete rest day can have zero exercise.', styles['Muted']), Spacer(1, 8),
              Paragraph('Weight-loss equivalent = weekly deficit / 7,700 kcal per kg. This rough conversion is not a prediction '
                        'of scale weight: water, glycogen, body composition and changing energy needs affect actual results.', styles['Muted'])]
    def footer(canvas, document):
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.HexColor('#566576'))
        canvas.drawString(36, 24, 'DietMCP | Personal weekly report | Nutrition and burn values are estimates')
        canvas.drawRightString(A4[0]-36, 24, str(document.page))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return out.getvalue()
