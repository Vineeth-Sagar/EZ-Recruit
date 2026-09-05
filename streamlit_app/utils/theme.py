"""
theme.py
Shared, theme-aware CSS for every page — cards, section headers, skill
tags, buttons. Centralized so a fix here doesn't need to be copy-pasted
into six near-duplicate <style> blocks again (which is how the bug below
survived unnoticed across every page).

Streamlit (1.40 here, and this project's requirements.txt only pins
streamlit>=1.35.0 with no upper bound, so the deployed version is
whatever's newest at install time) does not expose its active theme as a
CSS custom property, a DOM attribute, or a stable Python API —
`st.context.theme` does not exist on 1.40 (checked against the actual
installed package, not assumed) and no `--primary-color`-style variable
appears anywhere in its rendered stylesheets. So this module defines its
OWN CSS variables and switches them with a plain `prefers-color-scheme`
media query instead. That tracks the OS/browser preference, which is
Streamlit's own default ("Use system setting"); it won't follow a user
who manually forces Light or Dark from Streamlit's app menu against their
OS setting, since there's no supported hook to observe that override from
injected CSS on this version.

Bug this replaced: every card's inner text (.title, .label, etc.) relied
on inherited text color instead of setting one explicitly. Against a
hardcoded white card background, that happened to be legible when the
surrounding page was Streamlit's light theme, but on the dark theme the
inherited color was near-white-on-white — e.g. nav-card titles like
"History" and "Test Run" render nearly invisible. Confirmed by actually
running the app in a mobile+dark viewport rather than assuming the
hardcoded white cards were "fine because they render on a dark page
background" (they render fine as *boxes*; text inside them is the part
that broke). Every text rule below sets an explicit color for exactly
this reason.
"""
import streamlit as st

BASE_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

:root {
  --ob-card-bg: #ffffff;
  --ob-card-border: #e3e8f0;
  --ob-card-title: #16213e;
  --ob-card-text: #333333;
  --ob-card-subtext: #666666;
  --ob-accent: #1565c0;
  --ob-accent-dark: #0d47a1;
  --ob-tag-bg: #e3f2fd;
  --ob-tag-text: #1565c0;
}

@media (prefers-color-scheme: dark) {
  :root {
    --ob-card-bg: #1c2333;
    --ob-card-border: #333f52;
    --ob-card-title: #f4f6fb;
    --ob-card-text: #d7dbe4;
    --ob-card-subtext: #9aa2b1;
    --ob-accent: #5b9bf5;
    --ob-accent-dark: #3f7fdb;
    --ob-tag-bg: #1f3a5c;
    --ob-tag-text: #8ec3ff;
  }
}

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

.stat-card {
  background: var(--ob-card-bg);
  border-radius: 12px; padding: 1.2rem;
  box-shadow: 0 2px 8px rgba(0,0,0,0.08);
  border-left: 4px solid var(--ob-accent);
  text-align: center;
}
.stat-card .number { font-size: 1.8rem; font-weight: 700; color: var(--ob-accent); }
.stat-card .label  { color: var(--ob-card-subtext); font-size: 0.85rem; }

.nav-card {
  background: var(--ob-card-bg); border-radius: 12px; padding: 1.5rem;
  box-shadow: 0 2px 8px rgba(0,0,0,0.08); cursor: pointer;
  transition: all 0.2s; text-align: center; text-decoration: none;
  border: 2px solid transparent;
}
.nav-card:hover { border-color: var(--ob-accent); transform: translateY(-2px); }
.nav-card .icon  { font-size: 2.5rem; }
.nav-card .title { font-weight: 600; margin-top: 0.5rem; color: var(--ob-card-title); }
.nav-card .desc  { color: var(--ob-card-subtext); font-size: 0.85rem; }

.resume-card, .report-card {
  background: var(--ob-card-bg); border: 1px solid var(--ob-card-border);
  border-radius: 12px; padding: 1rem 1.5rem; margin-bottom: 0.8rem;
  color: var(--ob-card-text);
}
.resume-card:hover { border-color: var(--ob-accent); }
.report-card { display: flex; align-items: center; justify-content: space-between; }

.section-header {
  background: linear-gradient(135deg, var(--ob-accent), var(--ob-accent-dark));
  color: white; padding: 1rem 1.5rem; border-radius: 10px;
  margin: 1.5rem 0 1rem; font-weight: 600;
}

.skill-tag {
  display: inline-block; background: var(--ob-tag-bg); color: var(--ob-tag-text);
  padding: 3px 10px; border-radius: 20px; font-size: 0.8rem; margin: 2px;
  font-weight: 500;
}

.stButton > button {
  background: linear-gradient(135deg, var(--ob-accent), var(--ob-accent-dark));
  color: white; border: none; border-radius: 8px;
  padding: 0.5rem 2rem; font-weight: 600;
  transition: all 0.2s;
}
.stButton > button:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(21,101,192,0.4); }

/* Mobile: st.columns stacks cards vertically below ~640px, and at full
   desktop padding/font-size each one ends up taking most of a phone
   screen. Confirmed by actually testing at a 375px viewport, not
   assumed — 4 stat cards were each ~250px tall before this. */
@media (max-width: 480px) {
  .stat-card { padding: 0.8rem; }
  .stat-card .number { font-size: 1.4rem; }
  .stat-card .label  { font-size: 0.75rem; }
  .nav-card { padding: 1rem; }
  .nav-card .icon { font-size: 2rem; }
}
</style>
"""


def inject_base_css():
    """Call once near the top of every page, after st.set_page_config()."""
    st.markdown(BASE_CSS, unsafe_allow_html=True)
