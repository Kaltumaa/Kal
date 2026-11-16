"""Shared look & feel: one small stylesheet plus helpers built on native Streamlit components."""
from __future__ import annotations

import html
import re

import streamlit as st

CSS = """
<style>
/* ==========================================================================
   TALO — good advice, good yield
   Bone canvas · white panels · ink type · one green accent.
   Scratch-built for the Streamlit shell. No remote fonts, images or styles.
   ========================================================================== */

:root {
  --bg: #f0f0ea;
  --surface: #ffffff;
  --surface-2: #fafaf7;
  --surface-3: #f5f5f1;
  --ink: #121212;
  --ink-2: #4d4d49;
  --muted: #7b7b75;
  --faint: #a3a39c;
  --line: #e8e8e2;
  --line-strong: #d9d9d2;
  --green: #2f6417;
  --green-2: #4e8a2c;
  --green-deep: #173d22;
  --green-soft: #eef4e6;
  --lime: #8fc758;
  --amber: #96650f;
  --amber-soft: #fbf2df;
  --red: #a3412c;
  --red-soft: #f9ede9;
  --shadow-sm: 0 1px 2px rgba(23, 61, 34, 0.05);
  --shadow-md: 0 14px 38px rgba(23, 61, 34, 0.09);
  --shadow-card: 0 1px 2px rgba(23, 61, 34, 0.04), 0 10px 26px rgba(23, 61, 34, 0.045);
  --radius: 20px;
  --radius-sm: 14px;
  --font: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", Helvetica, Arial, sans-serif;
  --mono: "SFMono-Regular", "SF Mono", ui-monospace, Menlo, Consolas, "Liberation Mono", monospace;
}

/* ── Canvas ─────────────────────────────────────────────────────────────── */

.stApp,
[data-testid="stAppViewContainer"] {
  background:
    radial-gradient(900px 520px at 92% -6%, #fbfbf5 0%, rgba(251, 251, 245, 0) 62%),
    radial-gradient(760px 460px at -6% 104%, #e9efe1 0%, rgba(233, 239, 225, 0) 58%),
    var(--bg) !important;
}
[data-testid="stHeader"] { background: transparent !important; border: 0 !important; }
[data-testid="stDecoration"],
[data-testid="stStatusWidget"],
[data-testid="stAppDeployButton"],
footer { display: none !important; }

[data-testid="stMain"] { background: transparent !important; }
[data-testid="stMainBlockContainer"] {
  max-width: 1220px;
  width: calc(100% - 36px) !important;
  min-height: calc(100dvh - 104px);
  flex-shrink: 0;
  margin: 62px 18px 26px 18px;
  padding: 38px 42px 64px !important;
  background: var(--surface);
  border: 1px solid #e6e6de;
  border-radius: 26px;
  box-shadow: 0 1px 2px rgba(23, 61, 34, 0.05), 0 22px 60px rgba(23, 61, 34, 0.06);
  position: relative;
  overflow: hidden;
}
[data-testid="stMainBlockContainer"]::before {
  content: ""; position: absolute; inset: 0 0 auto 0; height: 4px;
  background: linear-gradient(90deg, var(--green) 0%, var(--green-2) 34%, var(--lime) 68%, rgba(143, 199, 88, 0) 100%);
  opacity: 0.9;
}
[data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] { gap: 1.6rem; }
[data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"]:has(h3, h4, h5) { margin-bottom: -1.35rem; }

/* ── Type ───────────────────────────────────────────────────────────────── */

/* The system stack, applied over Streamlit's bundled Source Sans. */
.stApp, .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6,
.stApp p, .stApp li, .stApp a, .stApp label, .stApp button,
.stApp input, .stApp textarea, .stApp select, .stApp th, .stApp td,
.stApp [data-testid="stMarkdownContainer"] { font-family: var(--font) !important; }

/* Micro-labels stay monospaced. */
.cp-kicker, .cp-muted, .cp-tag, .cp-legend, .cp-partners, .cp-status b,
.cp-row .lbl, .cp-entry .d, .cp-season small, .cp-stat span, .cp-ward .wn,
.stMarkdownBadge, .stApp code,
[data-testid="stMetricLabel"] p, [data-testid="stWidgetLabel"] p {
  font-family: var(--mono) !important;
}

.stApp, .stApp p, .stApp li, [data-testid="stMarkdownContainer"] { color: var(--ink-2); line-height: 1.6; }
.stApp b, .stApp strong { color: var(--ink); font-weight: 600; }
.stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5 {
  color: var(--ink) !important; font-weight: 600 !important; letter-spacing: -0.03em;
}
.stApp h1 { font-size: 2.9rem !important; line-height: 1.04 !important; }
.stApp h2 { font-size: 1.6rem !important; }
.stApp h3 { font-size: 1.3rem !important; }
.stApp [data-testid="stMainBlockContainer"] h3 {
  padding-left: 15px; position: relative;
}
.stApp [data-testid="stMainBlockContainer"] h3::before {
  content: ""; position: absolute; left: 0; top: 0.5em; width: 6px; height: 6px;
  border-radius: 50%; background: var(--lime); box-shadow: 0 0 0 3px rgba(143, 199, 88, 0.16);
}
.stApp h4 { font-size: 1.05rem !important; }
.stApp h5 { font-size: 0.95rem !important; }
[data-testid="stCaptionContainer"] p { color: var(--muted) !important; font-size: 0.78rem !important; line-height: 1.55; }
[data-testid="stWidgetLabel"] p {
  color: var(--muted) !important; font-size: 0.66rem !important; font-weight: 600 !important;
  text-transform: uppercase; letter-spacing: 0.085em;
}
.cp-muted {
  font-family: var(--mono); font-size: 0.64rem; font-weight: 500;
  text-transform: uppercase; letter-spacing: 0.07em; color: var(--muted);
}
hr { border: 0 !important; border-top: 1px solid var(--line) !important; margin: 1rem 0 !important; }
.stApp code {
  font-family: var(--mono); font-size: 0.85em; color: var(--ink);
  background: var(--surface-3); border: 1px solid var(--line);
  border-radius: 5px; padding: 0.05rem 0.3rem;
}

/* ── Page header ────────────────────────────────────────────────────────── */

.cp-head { padding: 0 0 20px; border-bottom: 1px solid var(--line); position: relative; }
.cp-head::after {
  content: ""; position: absolute; left: 0; bottom: -1px; width: 52px; height: 2px;
  background: linear-gradient(90deg, var(--green), var(--lime)); border-radius: 2px;
}
.cp-head .cp-kicker {
  display: inline-flex; align-items: center; gap: 8px;
  font-family: var(--mono); font-size: 0.63rem; font-weight: 500;
  text-transform: uppercase; letter-spacing: 0.11em; color: var(--green);
}
.cp-head .cp-kicker::before { content: ""; width: 18px; height: 1px; background: var(--green); }
.stApp .cp-head h1 {
  margin: 0.55rem 0 0.65rem; font-size: 2.9rem !important;
  line-height: 1.03 !important; letter-spacing: -0.045em !important;
}
.cp-head h1 .amp { color: var(--muted); font-weight: 500; }
.cp-head p { max-width: 46rem; margin: 0; font-size: 0.92rem; color: var(--ink-2); }
.cp-head.hero { padding-bottom: 10px; }
.cp-head.hero h1 { font-size: 3.45rem !important; margin-top: 0.7rem; }
.cp-head.hero p { font-size: 1rem; max-width: 49rem; }

/* ── Sections become quiet white cards ─────────────────────────────────── */

[class*="st-key-cp-section"] {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 22px 24px;
  box-shadow: var(--shadow-card);
}
[class*="st-key-cp-section"] > [data-testid="stVerticalBlock"] { gap: 0.9rem; }
[class*="st-key-cp-section"] [class*="st-key-cp-section"] {
  border: 0; padding: 0; box-shadow: none;
}
[class*="st-key-cp-topic"] { border-top: 1px solid var(--line); padding: 0.55rem 0; }
[class*="st-key-cp-topic"]:first-child { border-top: 0; }
[data-testid="stForm"] { border: 0 !important; padding: 0 !important; border-radius: 0 !important; background: transparent !important; }

/* ── Inputs ─────────────────────────────────────────────────────────────── */

[data-testid="stTextInputRootElement"],
[data-testid="stTextAreaRootElement"],
[data-testid="stNumberInputContainer"],
[data-testid="stDateInputField"],
[data-baseweb="select"] > div,
[data-baseweb="base-input"],
[data-baseweb="textarea"] {
  background: var(--surface) !important;
  border: 1px solid var(--line) !important;
  border-radius: 10px !important;
  box-shadow: none !important;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
[data-testid="stTextInputRootElement"],
[data-testid="stNumberInputContainer"],
[data-testid="stDateInputField"],
[data-baseweb="select"] > div { min-height: 40px; }
[data-testid="stTextInputRootElement"]:focus-within,
[data-testid="stTextAreaRootElement"]:focus-within,
[data-testid="stNumberInputContainer"]:focus-within,
[data-testid="stDateInputField"]:focus-within,
[data-baseweb="select"] > div:focus-within {
  border-color: var(--green) !important;
  box-shadow: 0 0 0 3px rgba(47, 112, 70, 0.12) !important;
}
.stApp input, .stApp textarea {
  color: var(--ink) !important; background: transparent !important;
  padding: 0.52rem 0.68rem !important; font-size: 0.84rem;
}
.stApp input::placeholder, .stApp textarea::placeholder { color: var(--faint) !important; }
[data-testid="stSelectbox"] [role="group"][data-rac] {
  background: var(--surface) !important;
  border: 1px solid var(--line) !important;
  border-radius: 10px !important;
  min-height: 40px;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
[data-testid="stSelectbox"] [role="group"][data-rac]:focus-within {
  border-color: var(--green) !important;
  box-shadow: 0 0 0 3px rgba(47, 112, 70, 0.12) !important;
}
[data-testid="stSelectbox"] input[role="combobox"] { padding: 0.35rem 0.55rem !important; }
[data-testid="stSelectbox"] button[aria-label="Open"] { color: var(--muted); }
[data-testid="stFileUploaderDropzone"], [data-testid="stAudioInput"] {
  background: var(--surface-2) !important;
  border: 1px dashed var(--line-strong) !important;
  border-radius: var(--radius-sm) !important;
  padding: 18px !important;
  transition: background 0.15s ease, border-color 0.15s ease;
}
[data-testid="stFileUploaderDropzone"]:hover {
  background: var(--green-soft) !important;
  border-color: var(--green-2) !important;
}
[data-testid="stFileUploaderDropzone"] button { margin-top: 8px; }
.stApp [data-testid="stCheckbox"] label, .stApp [data-testid="stRadio"] label { color: var(--ink-2); align-items: flex-start; }
.stApp [data-testid="stCheckbox"] p,
.stApp [data-testid="stRadio"] p { white-space: normal !important; overflow: visible !important; text-overflow: clip !important; }
.stApp [data-testid="stCheckbox"] [data-testid="stMarkdownContainer"],
.stApp [data-testid="stRadio"] [data-testid="stMarkdownContainer"] {
  overflow: visible !important; text-overflow: clip !important; white-space: normal !important;
}
.stApp input[type="checkbox"], .stApp input[type="radio"] { accent-color: var(--green); }

/* ── Buttons and links ──────────────────────────────────────────────────── */

.stApp button[data-testid^="stBaseButton"] {
  border-radius: 10px !important; box-shadow: none !important;
  font-weight: 600; font-size: 0.78rem; min-height: 38px;
  transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
}
.stApp button[data-testid="stBaseButton-secondary"],
.stApp button[data-testid="stBaseButton-secondaryFormSubmit"] {
  background: var(--surface-3); border: 1px solid transparent; color: var(--ink);
}
.stApp button[data-testid="stBaseButton-secondary"]:hover,
.stApp button[data-testid="stBaseButton-secondaryFormSubmit"]:hover { background: #e9e9e2; border-color: transparent; }
.stApp button[data-testid="stBaseButton-primary"],
.stApp button[data-testid="stBaseButton-primaryFormSubmit"] {
  background: linear-gradient(180deg, #232323 0%, #0e0e0e 100%);
  border: 1px solid #0e0e0e; color: #fff;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.14), 0 2px 6px rgba(17, 17, 17, 0.16);
}
.stApp button[data-testid="stBaseButton-primary"]:hover,
.stApp button[data-testid="stBaseButton-primaryFormSubmit"]:hover {
  background: linear-gradient(180deg, #14300f 0%, #0a1c07 100%);
  border-color: #0a1c07;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.16), 0 4px 12px rgba(23, 61, 34, 0.22);
}
.stApp button[data-testid="stBaseButton-primary"] p,
.stApp button[data-testid="stBaseButton-primaryFormSubmit"] p { color: #fff !important; }
.stApp button[data-testid="stBaseButton-tertiary"] {
  padding: 0 !important; min-height: 0 !important;
  background: transparent !important; border: 0 !important;
  justify-content: flex-start;
}
.stApp button[data-testid="stBaseButton-tertiary"] p {
  color: var(--green); font-weight: 600; font-size: 0.86rem;
  letter-spacing: -0.01em;
}
.stApp button[data-testid="stBaseButton-tertiary"]:hover p { color: #173d22; }
[data-testid="stPageLink"] a { padding-left: 0; background: transparent !important; }
[data-testid="stPageLink"] p {
  color: var(--green); font-weight: 600; font-size: 0.72rem;
  text-transform: uppercase; letter-spacing: 0.06em;
}
[data-testid="stPageLink"] [data-testid="stIconMaterial"] { color: var(--green); }
.stApp [data-testid="stMarkdownContainer"] a { color: var(--green); text-underline-offset: 2px; }
[data-testid="stDownloadButton"] button { border: 1px solid var(--line-strong) !important; background: var(--surface) !important; }

/* ── Sidebar ────────────────────────────────────────────────────────────── */

[data-testid="stSidebar"] {
  background:
    linear-gradient(180deg, #fcfcf7 0%, #f7f7f0 58%, #f2f4ea 100%) !important;
  border-right: 1px solid var(--line);
}
[data-testid="stSidebar"][aria-expanded="true"] {
  width: 272px !important;
  min-width: 272px !important;
}
[data-testid="stSidebar"][aria-expanded="false"] { min-width: 0 !important; }
[data-testid="stSidebar"] p, [data-testid="stSidebar"] span,
[data-testid="stSidebar"] label, [data-testid="stSidebar"] b { color: var(--ink); }
[data-testid="stSidebar"] svg { color: var(--ink); fill: var(--ink); }
[data-testid="stSidebarHeader"] { padding: 20px 18px 8px; }
[data-testid="stSidebarHeader"] > div { height: auto !important; }
[data-testid="stSidebarLogo"] {
  height: 76px !important; width: auto !important; max-height: 76px !important;
  margin-top: 0 !important;
}
[data-testid="stSidebarCollapseButton"] button { color: var(--muted) !important; }
[data-testid="stSidebarUserContent"] { padding: 16px 14px 20px; }
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {
  color: var(--muted) !important; font-size: 0.69rem !important; line-height: 1.5;
}
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p { color: var(--muted) !important; }
[data-testid="stSidebar"] [data-testid="stSelectbox"] [role="group"][data-rac] {
  min-height: 34px; border-radius: 9px !important;
}
[data-testid="stSidebar"] [data-testid="stSelectbox"] input[role="combobox"] {
  font-size: 0.78rem; padding: 0.22rem 0.5rem !important;
}
[data-testid="stSidebar"] [data-baseweb="select"] > div {
  background: var(--surface) !important; border-color: var(--line) !important; border-radius: 9px !important;
}
[data-testid="stSidebar"] [data-baseweb="select"] div,
[data-testid="stSidebar"] input { color: var(--ink) !important; -webkit-text-fill-color: var(--ink); }
[data-testid="stSidebar"] hr { border-top-color: var(--line) !important; }

/* Sidebar navigation: numbered rows, one filled row for the current page */
[data-testid="stSidebarNav"] { padding: 0 8px; }
[data-testid="stSidebarNavItems"] { counter-reset: nav; display: flex; flex-direction: column; gap: 2px; }
[data-testid="stSidebarNavLinkContainer"] { margin: 0; }
[data-testid="stSidebarNavLink"] {
  display: flex; align-items: center; gap: 10px;
  min-height: 40px; padding: 0 10px !important;
  border: 0 !important; border-radius: 10px;
  background: transparent !important;
  color: #5f5f5a !important;
  font-size: 0.8rem; font-weight: 500;
  counter-increment: nav;
  transition: background 0.15s ease, color 0.15s ease;
}
[data-testid="stSidebarNavLink"]::before {
  content: counter(nav, decimal-leading-zero);
  font-family: var(--mono); font-size: 0.57rem; font-weight: 500;
  color: var(--faint); width: 17px; flex: 0 0 auto; letter-spacing: 0;
}
[data-testid="stSidebarNavLink"] [data-testid="stIconMaterial"] { display: none; }
[data-testid="stSidebarNavLink"] span { color: inherit !important; opacity: 1; }
[data-testid="stSidebarNavLink"] p { color: inherit !important; font-size: inherit !important; font-weight: inherit; }
[data-testid="stSidebarNavLink"]:hover { background: rgba(255, 255, 255, 0.72) !important; color: var(--ink) !important; }
[data-testid="stSidebarNavLink"][aria-current="page"] {
  background: var(--surface) !important; color: var(--ink) !important; font-weight: 600;
  box-shadow: inset 0 0 0 1px var(--line), 0 1px 2px rgba(23, 61, 34, 0.05);
}
[data-testid="stSidebarNavLink"][aria-current="page"]::before { color: var(--green); }
[data-testid="stSidebarNavLink"][aria-current="page"]::after {
  content: ""; width: 6px; height: 6px; border-radius: 50%;
  background: var(--green); box-shadow: 0 0 0 3px var(--green-soft);
  margin-left: auto; flex: 0 0 auto;
}
[data-testid="stNavSectionHeader"] { padding: 16px 10px 5px; }
[data-testid="stNavSectionHeader"] p,
[data-testid="stNavSectionHeader"] span {
  font-family: var(--mono); font-size: 0.58rem !important; font-weight: 500 !important;
  text-transform: uppercase; letter-spacing: 0.11em; color: var(--faint) !important;
}
[data-testid="stNavSectionHeader"] [data-testid="stIconMaterial"] { display: none; }

/* ── Metrics as small stat tiles ────────────────────────────────────────── */

[data-testid="stMetric"] {
  background: linear-gradient(180deg, #ffffff 0%, #fbfbf7 100%);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  padding: 15px 16px;
  box-shadow: inset 0 1px 0 #fff, 0 1px 2px rgba(23, 61, 34, 0.04);
  position: relative;
  overflow: hidden;
}
[data-testid="stMetric"]::after {
  content: ""; position: absolute; left: 16px; top: 0; width: 26px; height: 2px;
  background: linear-gradient(90deg, var(--green), var(--lime));
  border-radius: 0 0 3px 3px;
}
[data-testid="stMetricLabel"],
[data-testid="stMetricLabel"] > div,
[data-testid="stMetricLabel"] p {
  white-space: normal !important;
  overflow: visible !important;
  text-overflow: clip !important;
}
[data-testid="stMetricLabel"] p {
  font-family: var(--mono) !important; font-size: 0.57rem !important; font-weight: 500;
  line-height: 1.35; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted) !important;
}
[data-testid="stMetricValue"] {
  font-size: 1.55rem !important; line-height: 1.15; font-weight: 600;
  color: var(--ink) !important; letter-spacing: -0.035em;
}
[data-testid="stMetricValue"] * {
  color: var(--ink) !important; white-space: normal !important;
  overflow: visible !important; text-overflow: clip !important; overflow-wrap: normal;
  word-break: normal !important;
}
[data-testid="stMetricDelta"] { font-size: 0.7rem !important; }
[data-testid="stMetricDelta"],
[data-testid="stMetricDelta"] > div,
[data-testid="stMetricDelta"] [data-testid="stMarkdownContainer"],
[data-testid="stMetricDelta"] p {
  max-width: none !important;
  overflow: visible !important;
  text-overflow: clip !important;
}
[data-testid="stMetricDelta"] p {
  white-space: normal !important;
  word-break: normal !important;
  font-size: 9.5px !important;
  line-height: 1.3;
}
[data-testid="stMetric"] div { overflow: visible !important; text-overflow: clip !important; }
[data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] > [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"] > [data-testid="stMetric"]) { gap: 10px; }
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"] { min-width: 0 !important; }

/* ── Expanders, alerts, tabs ────────────────────────────────────────────── */

[data-testid="stExpander"] {
  border: 1px solid var(--line) !important;
  border-radius: var(--radius-sm) !important;
  background: var(--surface);
  overflow: hidden;
}
[data-testid="stExpander"] details { border: 0 !important; }
[data-testid="stExpander"] summary { padding: 11px 15px !important; font-weight: 600; color: var(--ink); }
[data-testid="stExpander"] summary:hover { background: var(--surface-2); }
[data-testid="stExpanderDetails"] { padding: 0 15px 14px !important; }

[data-testid="stAlertContainer"], [data-testid="stAlert"] {
  border-radius: 12px !important;
  padding: 11px 14px !important;
  border: 1px solid var(--line);
  background: var(--surface-2) !important;
}
[data-testid="stAlertContainer"] p { color: var(--ink-2) !important; font-size: 0.8rem; margin: 0 !important; }
/* One quiet tinted card per alert instead of a white frame around a colour strip. */
[data-testid="stAlertContentInfo"], [data-testid="stAlertContentWarning"],
[data-testid="stAlertContentError"], [data-testid="stAlertContentSuccess"] {
  background: transparent !important; border: 0 !important; padding: 0 !important;
}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentInfo"]),
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentSuccess"]) {
  background: var(--green-soft) !important; border-color: #dbe9d8 !important;
}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentWarning"]) {
  background: var(--amber-soft) !important; border-color: #efe1c2 !important;
}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentError"]) {
  background: var(--red-soft) !important; border-color: #edd5cd !important;
}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentWarning"]) p,
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentError"]) p { color: var(--ink) !important; font-weight: 500; }
/* Streamlit wraps the tinted container in a second, empty frame. */
[data-testid="stAlert"] {
  background: transparent !important; border: 0 !important; padding: 0 !important;
}

/* The media picker on the scan pages reads as one framed area. */
[class*="st-key-cp-scan-media"] {
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  padding: 14px;
}
[class*="st-key-cp-scan-media"] [data-testid="stFileUploaderDropzone"] { background: var(--surface) !important; }

[data-testid="stTabs"] > div > div[role="tablist"] {
  gap: 3px; background: var(--surface-3); padding: 4px;
  border-radius: 10px; border: 1px solid var(--line); width: fit-content;
}
[data-testid="stTabs"] [data-testid="stTab"] {
  border-radius: 7px; padding: 5px 12px; height: 30px; font-size: 0.76rem;
  font-weight: 600; color: var(--muted); cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}
[data-testid="stTabs"] [data-testid="stTab"] p { font-size: 0.76rem; font-weight: 600; color: inherit !important; }
[data-testid="stTabs"] [data-testid="stTab"][data-selected="true"] {
  background: var(--surface); color: var(--ink); box-shadow: var(--shadow-sm);
}
/* The underline indicator that ships with the default tab skin. */
[data-testid="stTabs"] [data-testid="stTab"] > div[data-rac]:last-child:not([data-testid]) { display: none; }
[data-testid="stTabs"] [data-baseweb="tab-highlight"],
[data-testid="stTabs"] [data-baseweb="tab-border"] { display: none; }
[data-testid="stTabs"] [data-testid="stTabPanel"] { padding-top: 1rem; }

/* Segmented controls and pills */
[data-testid="stButtonGroup"] > div[role="radiogroup"] {
  gap: 3px; background: var(--surface-3); padding: 3px;
  border: 1px solid var(--line); border-radius: 10px; width: fit-content;
}
[data-testid="stButtonGroup"] button {
  border: 0 !important; border-radius: 7px !important; background: transparent !important;
  box-shadow: none !important; min-height: 30px; padding: 4px 11px !important;
  font-size: 0.76rem; font-weight: 600; color: var(--muted) !important;
}
[data-testid="stButtonGroup"] button[data-selected="true"] {
  background: var(--surface) !important; color: var(--ink) !important;
  box-shadow: var(--shadow-sm) !important;
}
[data-testid="stButtonGroup"] button p { color: inherit !important; font-size: inherit !important; }
[data-testid="stButtonGroup"] button[data-variant="pills"] {
  border: 1px solid var(--line) !important; border-radius: 999px !important;
  background: var(--surface) !important;
}
[data-testid="stButtonGroup"] button[data-variant="pills"][data-selected="true"] {
  background: var(--green-soft) !important; border-color: #cfe3cb !important; color: var(--green) !important;
}

/* ── Dataframes and charts ─────────────────────────────────────────────── */

[data-testid="stDataFrame"], [data-testid="stDataFrameResizable"] {
  border: 1px solid var(--line) !important; border-radius: var(--radius-sm) !important; overflow: hidden;
  box-shadow: 0 1px 2px rgba(23, 61, 34, 0.04);
}
[data-testid="stVegaLiteChart"], [data-testid="stArrowVegaLiteChart"],
[data-testid="stPlotlyChart"], [data-testid="stPydeckChart"] { border-radius: var(--radius-sm); overflow: hidden; }
[data-testid="stPydeckChart"] { border: 1px solid var(--line); }
[class*="st-key-cp-chart"] {
  background: linear-gradient(180deg, #ffffff 0%, #fcfcf9 100%);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  padding: 8px 14px 4px;
  box-shadow: var(--shadow-card);
}

/* ── Farmer advice hero ─────────────────────────────────────────────────── */

.cp-now {
  background: #121212; border: 1px solid #121212; border-radius: var(--radius);
  padding: 22px 24px; color: #fff; box-shadow: var(--shadow-md);
}
.cp-now .cp-kicker {
  font-family: var(--mono); font-size: 0.62rem; font-weight: 500;
  text-transform: uppercase; letter-spacing: 0.09em; color: #a9a9a1;
}
.cp-now .act {
  font-size: 2rem; line-height: 1.15; letter-spacing: -0.04em;
  font-weight: 600; margin: 0.45rem 0 0.55rem; color: #fff;
}
.cp-now .act.t-green { color: var(--lime); }
.cp-now .act.t-orange { color: #f1cd8f; }
.cp-now .act.t-gray { color: #fff; }
.cp-now p { margin: 0; font-size: 0.98rem; color: #c9c9c1; max-width: 46rem; }

/* ── Ward cards ─────────────────────────────────────────────────────────── */

.cp-wgrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(278px, 1fr)); gap: 14px; }
.cp-ward {
  display: flex; flex-direction: column; gap: 0.7rem;
  background: var(--surface); border: 1px solid var(--line);
  border-radius: var(--radius); padding: 18px;
  box-shadow: var(--shadow-card);
  transition: box-shadow 0.18s ease, transform 0.18s ease, border-color 0.18s ease;
}
.cp-ward:hover { transform: translateY(-1px); border-color: var(--line-strong); box-shadow: var(--shadow-md); }
.cp-ward .wn {
  font-family: var(--mono); font-size: 0.59rem; font-weight: 500;
  text-transform: uppercase; letter-spacing: 0.1em; color: var(--muted);
}
.cp-ward .act { font-weight: 600; font-size: 1.42rem; line-height: 1.15; letter-spacing: -0.035em; margin-top: -0.25rem; color: var(--ink); }
.cp-ward .act.t-gray { color: var(--ink); }
.cp-ward .why { color: var(--ink-2); font-size: 0.82rem; line-height: 1.55; }
.cp-ward .cp-row .cp-tag { font-size: 0.72rem; font-weight: 600; text-transform: none; letter-spacing: 0; }
.cp-stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 7px; }
.cp-stat { min-width: 0; background: var(--surface-2); border: 1px solid var(--line); border-radius: 10px; padding: 8px 9px; }
.cp-stat b { display: block; font-size: 0.92rem; font-weight: 600; color: var(--ink); white-space: nowrap; letter-spacing: -0.02em; }
.cp-stat span { font-family: var(--mono); font-size: 0.52rem; font-weight: 500; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); }
.cp-row { font-size: 0.78rem; color: var(--ink-2); line-height: 1.6; }
.cp-row .lbl {
  font-family: var(--mono); font-size: 0.54rem; font-weight: 500; text-transform: uppercase;
  letter-spacing: 0.06em; color: var(--muted); margin-right: 0.55rem;
  display: inline-block; min-width: 68px;
}
.cp-legend {
  display: flex; gap: 1.3rem; flex-wrap: wrap;
  font-family: var(--mono); font-size: 0.56rem; font-weight: 500;
  text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); padding: 0.8rem 0 0;
}
.cp-legend i { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 0.4rem; }
.cp-callout {
  padding: 13px 15px; margin: 0.6rem 0;
  border: 1px solid var(--line); border-radius: 12px;
  background: var(--surface-2); font-size: 0.8rem; color: var(--ink-2); line-height: 1.55;
}
.cp-callout.warn { background: var(--amber-soft); border-color: #efe1c2; color: #704d0d; }
.cp-crops { display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); gap: 12px; }
.cp-cropcard {
  display: flex; flex-direction: column; gap: 0.45rem;
  background: var(--surface); border: 1px solid var(--line);
  border-radius: var(--radius-sm); padding: 16px;
  box-shadow: var(--shadow-card);
  transition: box-shadow 0.18s ease, transform 0.18s ease, border-color 0.18s ease;
}
.cp-cropcard:hover { transform: translateY(-1px); border-color: var(--line-strong); box-shadow: var(--shadow-md); }
.cp-cropcard .cn { font-weight: 600; font-size: 1.05rem; letter-spacing: -0.025em; color: var(--ink); }
.cp-cropcard .meta { font-size: 0.76rem; color: var(--muted); }
.cp-prog { height: 5px; background: var(--surface-3); border-radius: 999px; overflow: hidden; }
.cp-prog span { display: block; height: 100%; background: var(--lime); border-radius: 999px; }
.cp-seasons { display: flex; align-items: baseline; gap: 1rem; flex-wrap: wrap; }
.cp-season small { display: block; font-family: var(--mono); font-size: 0.54rem; font-weight: 500; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); }
.cp-season b { font-size: 0.82rem; font-weight: 500; color: var(--ink-2); }
.cp-season.now b { color: var(--ink); font-weight: 600; }
.cp-arrow { color: var(--faint); }
.cp-entry { padding: 11px 0; border-top: 1px solid var(--line); }
.cp-entry:first-child { border-top: 0; }
.cp-entry .t { font-weight: 600; color: var(--ink); font-size: 0.82rem; }
.cp-entry .d { font-family: var(--mono); font-size: 0.55rem; font-weight: 500; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); }
.cp-entry .x { color: var(--ink-2); font-size: 0.8rem; margin-top: 0.2rem; }
.cp-sms { padding: 0.85rem 0; border-top: 1px solid var(--line); font-size: 0.8rem; }
.cp-step { display: flex; gap: 0.8rem; padding: 0.6rem 0; border-top: 1px solid var(--line); font-size: 0.78rem; }
.cp-step:first-child { border-top: 0; }
.cp-step code { background: none; border: 0; padding: 0; color: var(--ink); }
.cp-step .who { color: var(--muted); min-width: 110px; }
.cp-status {
  font-size: 0.7rem; color: var(--muted); line-height: 1.85;
  background: #f4f4ef; border: 1px solid #ededE6; border-radius: 12px; padding: 12px 13px;
}
.cp-status b { display: block; font-family: var(--mono); font-size: 0.56rem; font-weight: 500; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); margin-bottom: 2px; }
.cp-dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%; margin-right: 0.45rem; vertical-align: 1px; }
.cp-dot.ok { background: var(--green-2); box-shadow: 0 0 0 3px rgba(78, 138, 94, 0.12); }
.cp-dot.warn { background: #c08a2e; }
.cp-dot.bad { background: var(--red); }
.cp-partners {
  display: flex; flex-wrap: wrap; gap: 0.8rem 2.4rem; padding: 1.3rem 0 0; border-top: 1px solid var(--line);
  font-family: var(--mono); font-size: 0.56rem; font-weight: 500; text-transform: uppercase;
  letter-spacing: 0.08em; color: var(--faint); margin-top: 1.4rem;
}

/* ── Inline tags, chips and badges ─────────────────────────────────────── */

.cp-tag {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 3px 8px !important; border-radius: 999px;
  background: var(--surface-3) !important;
  border: 1px solid transparent;
  font-family: var(--mono); font-size: 0.57rem !important; font-weight: 500;
  text-transform: uppercase; letter-spacing: 0.05em;
  white-space: normal !important; overflow: visible !important; max-width: none !important;
}
.cp-tag::before {
  content: ""; width: 5px; height: 5px; border-radius: 50%;
  background: currentColor; margin: 0;
}
.cp-tag.t-green { background: var(--green-soft) !important; border-color: #dbe9d8; color: var(--green); }
.cp-tag.t-orange { background: var(--amber-soft) !important; border-color: #efe1c2; color: var(--amber); }
.cp-tag.t-red { background: var(--red-soft) !important; border-color: #edd5cd; color: var(--red); }
.cp-tag.t-gray { background: var(--surface-3) !important; color: var(--muted); }
.stMarkdownBadge {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 0 !important; background: transparent !important; border: 0;
  font-family: var(--mono); font-size: 0.57rem !important; font-weight: 500;
  text-transform: uppercase; letter-spacing: 0.05em;
  white-space: normal !important; overflow: visible !important; max-width: none !important;
}
.stMarkdownBadge::before {
  content: ""; width: 5px; height: 5px; border-radius: 50%;
  background: currentColor; margin: 0;
}
.cp-chip {
  display: inline-flex; align-items: center; padding: 2px 7px; margin: 0 5px 4px 0;
  border-radius: 999px; background: var(--surface-3);
  font-size: 0.68rem; font-weight: 500; color: var(--ink-2);
}
.cp-chip.red { background: var(--red-soft); color: var(--red); }
.cp-chip.ok { background: var(--green-soft); color: var(--green); }
.cp-chip.gray { background: var(--surface-3); color: var(--muted); }

/* ── Responsive ─────────────────────────────────────────────────────────── */

@media (max-width: 980px) {
  /* Side-by-side panes get too narrow here; stack them but keep metric tiles as a grid. */
  [data-testid="stHorizontalBlock"] { flex-wrap: wrap !important; }
  [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
    flex: 1 1 100% !important; width: 100% !important; min-width: 100% !important;
  }
}
@media (max-width: 900px) {
  [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] > [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"] > [data-testid="stMetric"]) {
    flex-wrap: wrap;
    gap: 10px;
  }
  [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] > [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"] > [data-testid="stMetric"]) > [data-testid="stColumn"] {
    flex: 1 1 44% !important;
    width: auto !important;
    min-width: 44% !important;
  }
  [data-testid="stMetricValue"] { font-size: 1.2rem !important; }
}
@media (max-width: 1100px) {
  [data-testid="stMainBlockContainer"] {
    margin: 58px 10px 16px; width: calc(100% - 20px) !important;
    padding: 28px 26px 48px !important; border-radius: 20px;
  }
  .cp-head.hero h1 { font-size: 2.9rem !important; }
}
@media (max-width: 760px) {
  [data-testid="stMainBlockContainer"] {
    margin: 56px 0 0; width: 100% !important;
    padding: 22px 16px 42px !important;
    border: 0; border-radius: 0; box-shadow: none;
  }
  .cp-head.hero h1 { font-size: 2.35rem !important; }
  .stApp h1 { font-size: 2.35rem !important; }
  .cp-wgrid { grid-template-columns: 1fr; }
  .cp-stats { grid-template-columns: repeat(3, 1fr); }
  [data-testid="stFilter"] { display: none; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { transition: none !important; animation: none !important; }
}

/* ── Scrollbars ─────────────────────────────────────────────────────────── */

* { scrollbar-width: thin; scrollbar-color: #d9d9d2 transparent; }
::-webkit-scrollbar { width: 9px; height: 9px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb {
  background: #d9d9d2; border-radius: 999px;
  border: 2px solid transparent; background-clip: padding-box;
}
</style>
"""

VERDICT_COLOR = {"PLANT": "green", "SPRAY": "orange", "HOLD": "orange"}
STATUS_TEXT = {"PENDING_REVIEW": "Awaiting signature", "SECURITY_LOCK": "Security lock",
               "NEEDS_DATA": "Needs field data", "APPROVED": "Sent", "REJECTED": "Rejected"}
STATUS_COLOR = {"PENDING_REVIEW": "orange", "SECURITY_LOCK": "red", "NEEDS_DATA": "gray", "APPROVED": "green",
                "REJECTED": "gray"}


def setup() -> None:
    st.session_state["_cp_sections"] = 0
    st.markdown(CSS, unsafe_allow_html=True)


def section(parent=None):
    """A block of related content: no box, just a faint rule above it (replaces a bordered container)."""
    st.session_state["_cp_sections"] = st.session_state.get("_cp_sections", 0) + 1
    return (parent or st).container(key=f"cp-section-{st.session_state['_cp_sections']}")


def partners() -> None:
    """What the system runs on, as one flat row."""
    items = ["Qwen 2.5", "Moondream 2", "Whisper", "Ollama", "LangGraph", "MCP", "FastAPI", "SQLite", "Streamlit"]
    st.markdown('<div class="cp-partners">' + "".join(f"<span>{i}</span>" for i in items) + "</div>",
                unsafe_allow_html=True)


def header(title: str, subtitle: str, hero: bool = False) -> None:
    """Page header. Only landing pages get the large version, so working pages start with the work."""
    role = st.session_state.get("role")
    kicker = {"farmer": "TALO · Good advice, good yield", "institution": "TALO · Institution",
              "officer": "TALO · Dagoretti South extension desk · Short rains 2026"}.get(role,
                                                                                     "TALO · Good advice, good yield")
    title_html = html.escape(title).replace("&amp;", '<span class="amp">&amp;</span>')
    st.markdown(f'<div class="cp-head{" hero" if hero else ""}"><div class="cp-kicker">{kicker}</div>'
                f'<h1>{title_html}</h1><p>{html.escape(subtitle)}</p></div>', unsafe_allow_html=True)


def show_rationale(text: str | None) -> None:
    """A draft's reasoning in parts: the decision, why, plot history, the season, and the AI's own words folded away."""
    parts = re.split(r"\s(?=Plot history |Weather pattern: |Model: |Self-check problems: )", (text or "").strip())
    head, _, why = parts[0].partition(". ")
    if why and head.split(":")[0] in ("PLANT", "SPRAY", "HOLD"):
        st.markdown(f"#### {head}")
    else:
        why = parts[0]
    if why:
        st.markdown(why)
    for part in parts[1:]:
        if part.startswith("Plot history "):
            st.markdown(f"**Plot history.** {part[len('Plot history '):]}")
        elif part.startswith("Weather pattern: "):
            st.markdown(f"**This season.** {part[len('Weather pattern: '):]}")
        elif part.startswith("Model: "):
            with st.expander("The AI's explanation (not checked by the rules)"):
                st.markdown(part[len("Model: "):])
        else:
            st.warning(part)


def latest_advice(advisories: list[dict]) -> None:
    """The first thing a farmer sees: their officer's latest signed advice. Never a draft."""
    sent = [a for a in advisories if a["status"] == "APPROVED"]
    if not sent:
        st.markdown('<div class="cp-now"><div class="cp-kicker">This week</div><div class="act">No advice yet</div>'
                    '<p>When your extension officer signs advice for your farm, it appears here and comes by SMS.</p>'
                    '</div>', unsafe_allow_html=True)
        return
    a = max(sent, key=lambda x: x.get("reviewed_at") or "")
    word, color = {"PLANT": ("Plant now", "green"), "SPRAY": ("Scout, then spray", "orange"),
                   "HOLD": ("Wait for now", "orange")}.get(a["verdict"], ("Advice", "gray"))
    langs = (a.get("sent_languages") or "en").split(",")
    message = a["farmer_message"] if "en" in langs or not a.get("farmer_message_sw") else a["farmer_message_sw"]
    st.markdown(f'<div class="cp-now"><div class="cp-kicker">From {html.escape(a["officer_signature"] or "your officer")}'
                f' · {html.escape((a.get("reviewed_at") or "")[:10])}</div>'
                f'<div class="act t-{color}">{word}</div><p>{html.escape(message or "")}</p></div>',
                unsafe_allow_html=True)


def badges(verdict: str | None, status: str) -> str:
    """Verdict and status as inline markdown badges on one line."""
    return (f":{VERDICT_COLOR.get(verdict, 'gray')}-badge[{verdict or 'No advice'}] "
            f":{STATUS_COLOR.get(status, 'gray')}-badge[{STATUS_TEXT.get(status, status)}]")


# --- Plain-language labels ----------------------------------------------------------------------------------
GUIDE_TITLES = {"pest_action_thresholds.md": "Pest action guide", "pesticides_safety.md": "Pesticide safety guide",
                "crop_calendar_nairobi.md": "Crop calendar guide", "spray_safety_guidelines.md": "Spray safety guide",
                "pests_diseases.md": "Pests & diseases guide", "chirps_dekadal_dagoretti.csv": "Rainfall history (CHIRPS-style)",
                "season_outlook.csv": "Season rainfall outlook"}
STAGES = {"PRE_PLANTING": "Not planted yet", "EMERGENCE": "Just emerged", "EARLY_VEGETATIVE": "Young plants",
          "LATE_VEGETATIVE_TASSELING": "Tall plants / tasseling", "GRAIN_FILL": "Grain filling", "MATURITY": "Maturing",
          "HARVEST_READY": "Ready to harvest", "VEGETATIVE": "Growing leaves", "FLOWERING": "Flowering",
          "POD_FILL": "Pods filling", "ESTABLISHMENT": "Establishing", "CONTINUOUS_HARVEST": "Harvesting leaves",
          "TUBER_INITIATION": "Tubers starting", "TUBER_BULKING": "Tubers growing", "UNKNOWN": "Unknown stage"}
FLAG_TEXT = {
    "auto_filled": "The AI skipped a step, so the system fetched it automatically",
    "corrected_args": "The AI used a wrong value in a step; the system corrected it",
    "model_disagreement": "The AI suggested different advice; the safety rules decided",
    "data_repaired": "Messy farm record was cleaned up",
    "prompt_injection_detected": "Suspicious instructions found in the record and removed",
    "false_start_risk": "Rain follows a dry spell (false-start risk)",
    "rotation_risk": "Same crop family planted again (pest carry-over risk)",
    "self_check_retry": "The self-check found a problem and re-gathered the evidence",
    "self_check_failed": "The self-check failed twice; draft withheld",
    "llm_unavailable_deterministic_gathering": "Local AI was offline; fixed rules were used",
    "weather_forecast_stale": "The rain forecast is out of date",
    "blocked_tool_request": "The AI asked for a tool it is not allowed to use (blocked)",
    "llm_skipped_status_needs_data": "Not enough farm data, so no AI text was written",
    "llm_skipped_status_security_lock": "Record locked, so no AI text was written",
    "sw_template": "Kiswahili message uses fixed template wording",
    "sw_model_translation": "Kiswahili message translated by the local model",
    "sw_translation_failed": "The local model could not translate to Kiswahili; template used",
    "sw_translation_rejected": "The model's Kiswahili changed a number or name; template used",
}


SPRAY_COLOUR = {"NO_RAIN": "red", "RAIN_SOON": "orange", "NO_WIND": "orange", "CAREFUL": "orange", "OK": "green"}
OLD_SPRAY_LABEL = {"UNSAFE": ("Don't spray (rain)", "red"), "CAUTION": ("Careful: only if no rain for 6 h", "orange"),
                   "SAFE": ("OK", "green")}


def voice_note(key: str) -> dict | None:
    """A record button: the farmer picks the language they will speak, records, and gets text to check.
    Returns the transcription (text, suggested_action) once, or None."""
    import base64

    import api_client as api
    with st.expander("Record a voice note instead of typing", expanded=False):
        try:
            status = api.speech_status()
        except api.ApiError:
            status = {"available": False}
        if not status.get("available"):
            st.caption("Voice notes need the speech model on this computer. Type your note below instead.")
            return None
        c = st.columns([1, 2], vertical_alignment="bottom")
        lang = c[0].selectbox("I will speak in", ["sw", "en", "auto"], key=f"{key}-lang",
                              format_func={"sw": "Kiswahili", "en": "English", "auto": "Let the app detect"}.get)
        audio = c[1].audio_input("Record", key=f"{key}-audio")
        st.caption("The recording is turned into text on this computer and nothing is saved until you press Save. "
                   "Sheng and other local languages are not supported yet. The first recording takes longer while "
                   "the speech model loads.")
        if audio is not None and st.button("Turn my voice into text", key=f"{key}-go", icon=":material/subtitles:"):
            with st.spinner("Listening…"):
                try:
                    r = api.transcribe(base64.b64encode(audio.getvalue()).decode(), None if lang == "auto" else lang)
                except api.ApiError as exc:
                    st.error(str(exc.detail))
                    return None
            if r.get("flagged") or not r.get("text"):
                st.warning("No usable text came out of that recording. Try again closer to the phone, or type it.")
                return None
            st.success(f"Heard: “{r['text']}”. Check it in the box below and edit it before saving.")
            return r
    return None


def language_defaults(plot: dict) -> tuple[bool, bool, str]:
    """(send English, send Kiswahili, caption) from the farmer's preferred language and when they last used the app."""
    pref = plot.get("language") or "en"
    seen = plot.get("farmer_last_seen")
    words = {"en": "English", "sw": "Kiswahili", "both": "English and Kiswahili"}[pref]
    app = f"last opened the app {seen[:10]}" if seen else "has not opened the app"
    return (pref in ("en", "both"), pref in ("sw", "both"),
            f"Farmer prefers **{words}** and {app}. The message goes by SMS either way (no internet needed).")


def spray_status(z: dict) -> tuple[str, str]:
    """(label, colour) for 'can you spray?'. The backend decides it (rainfall_outlook); this only picks a colour.
    Drafts saved before the backend sent a status fall back to the rain band alone."""
    if z.get("spray_label"):
        return z["spray_label"], SPRAY_COLOUR.get(z.get("spray_status"), "orange")
    return OLD_SPRAY_LABEL.get(z.get("spray_band"), ("—", "orange"))


def stage_label(stage: str | None) -> str:
    return STAGES.get(stage or "", (stage or "—").replace("_", " ").title())


def source_label(src: str, names: dict | None = None) -> str:
    kind, _, ref = src.partition(":")
    if kind == "plots":
        return f"Farm record ({(names or {}).get(ref, ref)})"
    if kind == "weather_cache":
        zone, _, issued = ref.partition("@")
        return f"Rain forecast for {zone.title()}" + (f" (issued {issued[:10]})" if issued else "")
    if kind == "pest_alerts":
        return f"Confirmed pest report {ref}"
    if kind == "reference":
        return GUIDE_TITLES.get(ref, ref)
    return src


def flag_label(flag: str) -> str:
    return FLAG_TEXT.get(flag.split(":")[0], flag.replace("_", " "))


def names() -> dict:
    return st.session_state.get("farm_names", {})


def farm_label(hid: str | None) -> str:
    if not hid:
        return "—"
    info = st.session_state.get("farm_info", {}).get(hid, {})
    zone = (info.get("zone_id") or "").title()
    return f"{names().get(hid, hid)}" + (f" · {zone}" if zone else "")


# --- Urgency and citations ------------------------------------------------------------------------------------
HARVEST_STAGES = {"MATURITY", "HARVEST_READY", "HARVEST", "POD_FILL_MATURITY", "TUBER_BULKING"}
URGENCY = {"PLANT": ("When to plant: plant now", "green"), "SPRAY": ("When to spray: spray now", "orange"),
           "HOLD": ("When to hold: hold", "orange"), "HARVEST": ("Ready for harvest", "green")}


def urgency(verdict: str | None, stage: str | None) -> tuple[str, str]:
    """Display state from the verdict plus the crop calendar. Harvest readiness is shown, never decided by the AI."""
    if verdict in (None, "HOLD") and stage in HARVEST_STAGES:
        return URGENCY["HARVEST"]
    return URGENCY.get(verdict or "", ("No advice yet", "gray"))


def suggested_citation(adv: dict, field_log: list[dict] | None = None) -> str:
    """A citation built from the draft's own records, for the officer to check before sending."""
    ev = adv.get("evidence") or {}
    rain, plot, pattern = ev.get("rain") or {}, ev.get("plot") or {}, ev.get("weather_pattern") or {}
    srcs = adv.get("sources") or []
    wx = next((x for x in srcs if x.startswith("weather_cache:")), None)
    pl = next((x for x in srcs if x.startswith("plots:")), None)
    pest = next((x for x in srcs if x.startswith("pest_alerts:")), None)
    parts = []
    if wx:
        parts.append(f"{rain.get('rain_7d_mm', '?')} mm 7-day rain forecast ({wx})")
    if pattern.get("season_anomaly_pct") is not None:
        parts.append(f"season outlook {pattern['season_anomaly_pct']:+d}% vs normal")
    if pl:
        day = plot.get("days_since_planting")
        parts.append(f"plot record {pl} ({plot.get('active_crop') or 'no crop'}"
                     + (f", day {day})" if day is not None else ")"))
    if pest:
        parts.append(f"confirmed pest report {pest}")
    if field_log:
        parts.append(f"plot history entry ID: {field_log[0]['id']}")
    return "Citing " + ", ".join(parts) if parts else ""


def search_markdown(md: str, query: str) -> str | None:
    """The parts of a guide that mention the search words: matching sections, and only the matching rows of a
    table (with its header). None if nothing matches."""
    words = [w for w in query.lower().split() if w]
    hit = lambda text: all(w in text.lower() for w in words)              # noqa: E731
    sections, cur = [], []
    for line in md.splitlines():
        if line.startswith("#") and cur:
            sections.append(cur)
            cur = []
        cur.append(line)
    sections.append(cur)
    out = []
    for sec in sections:
        if not hit("\n".join(sec)):
            continue
        head = [l for l in sec if l.startswith("#")]
        table = [l for l in sec if l.lstrip().startswith("|")]
        rows = [l for l in table[2:] if hit(l)]
        if table and rows and not hit("\n".join(l for l in sec if l not in table)):
            out.append("\n".join(head + [""] + table[:2] + rows))       # just the matching table rows
        else:
            out.append("\n".join(sec))
    return "\n\n".join(out) if out else None
