"""HTML rendering of a :class:`WeeklyReport`, for the weekly e-mail.

Written from the report's figures rather than converted from the Markdown: the
e-mail keeps a table of four columns where the Markdown file has seven, because
a wide table is unreadable on a phone.

Every rule is an inline ``style`` attribute. A ``<style>`` block in the head is
stripped by several clients, Outlook among them, and the message would arrive
unformatted — which is exactly what happened with the Markdown conversion.
"""

from __future__ import annotations

from html import escape

from .format import decimal, family_label, fr_date, signed, variation_pct
from .weekly import SkillTrend, WeeklyReport

# Une seule échelle de gris, plus un ambre pour les chiffres qui alertent.
INK = "#1f2933"
MUTED = "#6b7280"
RULE = "#e2e8f0"
HEAD_BG = "#f1f5f9"
ACCENT = "#b45309"

_BODY = f"font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:{INK};"
_WRAP = "max-width:680px;margin:0 auto;padding:8px 16px 24px;"
_H1 = f"font-size:20px;line-height:1.3;margin:0 0 4px;color:{INK};"
_H2 = f"font-size:16px;margin:28px 0 6px;padding-bottom:4px;border-bottom:2px solid {RULE};"
_NOTE = f"font-size:13px;color:{MUTED};margin:0 0 12px;line-height:1.5;"
_TABLE = "border-collapse:collapse;width:100%;font-size:14px;"
_TH = f"text-align:left;padding:8px 10px;background:{HEAD_BG};border-bottom:2px solid {RULE};font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:{MUTED};"
_TH_NUM = _TH + "text-align:right;"
_TD = f"padding:8px 10px;border-bottom:1px solid {RULE};"
_TD_NUM = _TD + "text-align:right;white-space:nowrap;"
_TD_GROWTH = _TD_NUM + f"font-weight:700;color:{ACCENT};"
_STAT = f"font-size:15px;margin:0 0 6px;line-height:1.5;"


def _alert_row(trend: SkillTrend) -> str:
    """One line of the alert table: skill, offers, share, growth."""
    return (
        "<tr>"
        f'<td style="{_TD}"><strong>{escape(trend.competence)}</strong>'
        f'<div style="font-size:12px;color:{MUTED};">{escape(family_label(trend.famille))}</div></td>'
        f'<td style="{_TD_NUM}">{trend.previous_offers} &rarr; {trend.current_offers}</td>'
        f'<td style="{_TD_NUM}">{decimal(trend.previous_share_pct)} %'
        f" &rarr; {decimal(trend.current_share_pct)} %</td>"
        f'<td style="{_TD_GROWTH}">{signed(trend.growth_pct)}</td>'
        "</tr>"
    )


def _alert_table(trends: list[SkillTrend]) -> str:
    return (
        f'<table role="presentation" style="{_TABLE}">'
        "<thead><tr>"
        f'<th style="{_TH}">Compétence</th>'
        f'<th style="{_TH_NUM}">Offres</th>'
        f'<th style="{_TH_NUM}">Part des offres</th>'
        f'<th style="{_TH_NUM}">Croissance</th>'
        "</tr></thead><tbody>" + "".join(_alert_row(t) for t in trends) + "</tbody></table>"
    )


def _emerging_list(trends: list[SkillTrend]) -> str:
    """Emerging skills as a list: a four-column table would say little here."""
    items = "".join(
        f'<li style="margin-bottom:6px;"><strong>{escape(t.competence)}</strong> — '
        f"{t.current_offers} offres "
        f'<span style="color:{MUTED};">({t.previous_offers} la semaine précédente, '
        f"{escape(family_label(t.famille))})</span></li>"
        for t in trends
    )
    return f'<ul style="margin:0;padding-left:20px;font-size:14px;line-height:1.5;">{items}</ul>'


def to_html(report: WeeklyReport) -> str:
    """Render the report as the HTML body of the weekly e-mail."""
    settings = report.settings
    measure = "part des offres" if settings.measure == "part" else "nombre d'offres"
    variation = variation_pct(report.previous_offers, report.offers)

    alerts = (
        _alert_table(report.alerts)
        if report.alerts
        else f'<p style="{_STAT}">Aucune alerte cette semaine.</p>'
    )
    emerging = (
        _emerging_list(report.emerging)
        if report.emerging
        else f'<p style="{_STAT}">Aucune compétence émergente cette semaine.</p>'
    )

    return (
        f'<div style="{_BODY}">'
        f'<div style="{_WRAP}">'
        f'<h1 style="{_H1}">Radar Tech FR</h1>'
        f'<p style="{_NOTE}">Semaine du {fr_date(report.week_start)} '
        f"au {fr_date(report.week_end)}</p>"
        f'<p style="{_STAT}"><strong>{report.offers} offres publiées</strong> '
        f'<span style="color:{MUTED};">({signed(variation)} par rapport aux '
        f"{report.previous_offers} de la semaine précédente)</span></p>"
        f'<p style="{_STAT}"><strong>{report.alternance_offers}</strong> '
        f'<span style="color:{MUTED};">en alternance</span></p>'
        f'<h2 style="{_H2}">Alertes</h2>'
        f'<p style="{_NOTE}">Croissance de plus de {settings.growth_threshold_pct:g} % '
        f"en {measure}, parmi les compétences citées par au moins "
        f"{settings.min_previous_offers} offres la semaine précédente.</p>"
        f"{alerts}"
        f'<h2 style="{_H2}">Compétences émergentes</h2>'
        f'<p style="{_NOTE}">Moins de {settings.min_previous_offers} offres la semaine '
        f"précédente, au moins {settings.min_emerging_offers} cette semaine.</p>"
        f"{emerging}"
        f'<p style="{_NOTE}margin-top:28px;border-top:1px solid {RULE};padding-top:12px;">'
        "Source : API Offres d'emploi v2 de France Travail. Les semaines sont celles de "
        "création des offres ; une offre retirée avant la collecte n'est pas comptée.</p>"
        "</div></div>"
    )
