import streamlit as st
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import pandas as pd
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict

# ───────────────────────── CSS (reuse your style.css if exists) ─────────────────────────
def local_css(file_name):
    try:
        with open(file_name) as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    except:
        pass

local_css("style.css")

st.markdown(
    "<p class='h1'>Broken <span>Link Checker</span></p>",
    unsafe_allow_html=True
)

st.markdown("Scan your website for broken, redirected or problematic links — live updates & export")

# ───────────────────────── INPUTS ─────────────────────────
col1, col2 = st.columns(2)
with col1:
    start_url = st.text_input(
        "Starting URL",
        value="https://example.com",
        placeholder="https://yourwebsite.com"
    )

with col2:
    max_pages = st.number_input("Max Pages to Crawl", 10, 300, 80, step=10)

col1, col2 = st.columns(2)
with col1:
    max_workers = st.number_input("Concurrent Checks", 4, 16, 8, step=2)

with col2:
    check_external = st.checkbox("Check External Links too (slower)", value=False)

if st.button("Start Scan", type="primary"):

    if not start_url.startswith(("http://", "https://")):
        st.error("Please enter a full URL[](https://...)")
        st.stop()

    domain = urlparse(start_url).netloc
    visited = set()
    to_visit = [start_url.strip()]
    results: List[Dict] = []
    page_count = 0
    link_check_count = 0

    status = st.empty()
    phase_indicator = st.empty()
    progress = st.progress(0)
    eta_text = st.empty()
    table = st.empty()

    start_time = time.time()
    page_times = []  # for ETA

    phase_indicator.markdown("**🔍 Phase 1 – Crawling & Discovering Links**")

    while to_visit and page_count < max_pages:
        current_url = to_visit.pop(0)
        if current_url in visited:
            continue

        visited.add(current_url)
        page_count += 1

        page_start = time.time()

        status.markdown(f"**Scanning page {page_count}/{max_pages}**  \n{current_url}")

        try:
            resp = requests.get(current_url, timeout=12, allow_redirects=True)
            page_time = time.time() - page_start
            page_times.append(page_time)

            if resp.status_code >= 400:
                results.append({
                    "Page": current_url,
                    "Link": current_url,
                    "Type": "Page itself",
                    "Status Code": resp.status_code,
                    "Status": "Broken"
                })
            else:
                soup = BeautifulSoup(resp.text, "html.parser")

                for a_tag in soup.find_all("a", href=True):
                    href = a_tag["href"].strip()
                    if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                        continue

                    abs_url = urljoin(current_url, href)
                    parsed = urlparse(abs_url)

                    if parsed.scheme not in ("http", "https"):
                        continue

                    link_domain = parsed.netloc
                    is_internal = (link_domain == domain or link_domain == f"www.{domain}")

                    if not check_external and not is_internal:
                        continue

                    link_type = "Internal" if is_internal else "External"

                    # Quick HEAD check
                    try:
                        head = requests.head(abs_url, timeout=7, allow_redirects=True)
                        code = head.status_code
                    except:
                        code = "Error"

                    status_str = "OK"
                    if isinstance(code, int):
                        if code >= 400:
                            status_str = "Broken"
                        elif code in (301, 302, 307, 308):
                            status_str = "Redirect"
                    else:
                        status_str = "Error"

                    results.append({
                        "Page": current_url,
                        "Link": abs_url,
                        "Type": link_type,
                        "Status Code": code,
                        "Status": status_str
                    })

                    link_check_count += 1

                    if is_internal and abs_url not in visited and abs_url not in to_visit:
                        to_visit.append(abs_url)

            # Live table update every page
            if results:
                df_live = pd.DataFrame(results)
                table.dataframe(df_live, use_container_width=True)

            # Progress & ETA
            progress_val = min(page_count / max_pages, 0.98)
            progress.progress(progress_val)

            if len(page_times) >= 3:
                avg_page_time = sum(page_times[-5:]) / min(len(page_times), 5)
                remaining_pages = max_pages - page_count
                eta_sec = remaining_pages * avg_page_time
                eta_min = eta_sec / 60
                eta_text.markdown(f"**ETA remaining**: ≈ {eta_min:.1f} min ({int(eta_sec)} sec)")

        except Exception as e:
            results.append({
                "Page": current_url,
                "Link": current_url,
                "Type": "Page itself",
                "Status Code": "Error",
                "Status": f"Failed ({str(e)[:50]})"
            })
            if results:
                table.dataframe(pd.DataFrame(results), use_container_width=True)

        # Small random delay to be polite
        time.sleep(random.uniform(0.4, 1.2))

    # ────────────────────────────────────────
    #               SUMMARY & EXPORT
    # ────────────────────────────────────────

    total_time = time.time() - start_time

    df = pd.DataFrame(results)

    broken = df[df["Status"].str.contains("Broken|Error", case=False, na=False)]
    redirects = df[df["Status"].str.contains("Redirect", na=False)]

    phase_indicator.markdown("**✅ Scan Complete**")
    status.success(
        f"**Finished!** Crawled **{len(visited)}** pages • Found **{len(broken)}** broken links  \n"
        f"Total time: {total_time:.1f} seconds"
    )

    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Pages Crawled", len(visited))
    col_b.metric("Broken / Error", len(broken))
    col_c.metric("Redirects", len(redirects))

    tab_all, tab_broken, tab_redirect = st.tabs(["📋 All Links", "⚠️ Broken Only", "↪️ Redirects"])

    with tab_all:
        st.dataframe(df.sort_values(["Status", "Page"]), use_container_width=True, hide_index=True)

    with tab_broken:
        if broken.empty:
            st.success("No broken links detected — great job! 🎉")
        else:
            st.dataframe(broken.sort_values("Page"), use_container_width=True, hide_index=True)

    with tab_redirect:
        if redirects.empty:
            st.info("No redirects found")
        else:
            st.dataframe(redirects.sort_values("Page"), use_container_width=True, hide_index=True)

    # Download
    csv = df.to_csv(index=False).encode('utf-8')
    st.download_button(
        "📥 Download Full Report (CSV)",
        csv,
        f"broken-links-{domain.replace('.', '_')}.csv",
        "text/csv"
    )

    st.caption("Tip: For big sites → use sitemap.xml or limit to important sections.")
