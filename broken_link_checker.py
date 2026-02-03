import streamlit as st
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
from typing import List, Dict

st.set_page_config(page_title="Broken Link Checker", layout="wide")

st.title("🔗 Broken Link Checker")
st.markdown("""
Scan internal pages of a website and find broken, redirected or problematic links.  
**Limits:** max 150 pages, 10 concurrent checks — suitable for Streamlit Cloud.
""")

# ────────────────────────────────────────
#               INPUTS
# ────────────────────────────────────────

col1, col2, col3 = st.columns([3, 2, 2])

with col1:
    start_url = st.text_input(
        "Starting URL (must be full https://...)",
        value="https://example.com",
        placeholder="https://yourwebsite.com"
    )

with col2:
    max_pages = st.number_input("Max pages to crawl", 10, 300, 80, step=10)

with col3:
    max_workers = st.number_input("Concurrent checks", 5, 20, 10, step=5)

check_external = st.checkbox("Also check external links (slower)", value=False)
follow_redirects = st.checkbox("Treat redirects as OK (301/302/307)", value=True)

if st.button("Start Scan", type="primary"):

    if not start_url.startswith(("http://", "https://")):
        st.error("Please enter a valid full URL starting with https:// or http://")
        st.stop()

    # ────────────────────────────────────────
    #               CRAWLER STATE
    # ────────────────────────────────────────

    visited = set()
    to_visit = [start_url.strip()]
    results: List[Dict] = []
    domain = urlparse(start_url).netloc

    progress_bar = st.progress(0)
    status_text = st.empty()
    result_container = st.container()

    start_time = time.time()

    with st.spinner("Crawling pages..."):
        page_count = 0

        while to_visit and page_count < max_pages:
            current_url = to_visit.pop(0)

            if current_url in visited:
                continue

            visited.add(current_url)
            page_count += 1

            status_text.markdown(f"**Scanning page {page_count}/{max_pages}**: {current_url}")

            try:
                resp = requests.get(current_url, timeout=12, allow_redirects=True)
                if resp.status_code >= 400:
                    results.append({
                        "Page": current_url,
                        "Link": current_url,
                        "Type": "Self (page itself)",
                        "Status Code": resp.status_code,
                        "Status": "Broken" if resp.status_code >= 400 else "OK"
                    })
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")
                links_found = 0

                for a in soup.find_all("a", href=True):
                    href = a["href"].strip()
                    if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                        continue

                    abs_url = urljoin(current_url, href)
                    parsed = urlparse(abs_url)

                    if not parsed.scheme in ("http", "https"):
                        continue

                    link_domain = parsed.netloc

                    is_internal = link_domain == domain or link_domain == f"www.{domain}"

                    # Skip external if not wanted
                    if not check_external and not is_internal:
                        continue

                    link_type = "Internal" if is_internal else "External"

                    # ─── Check link status ────────────────────────────────
                    try:
                        head_resp = requests.head(
                            abs_url,
                            timeout=8,
                            allow_redirects=follow_redirects
                        )
                        code = head_resp.status_code
                    except Exception:
                        # fallback GET
                        try:
                            get_resp = requests.get(abs_url, timeout=8, stream=True)
                            code = get_resp.status_code
                        except Exception:
                            code = "Timeout / Connection Error"

                    status_str = "OK"
                    if isinstance(code, int):
                        if code >= 400:
                            status_str = "Broken"
                        elif code in (301, 302, 307, 308):
                            status_str = "Redirect" if not follow_redirects else "OK (redirect)"
                    else:
                        status_str = "Error"

                    results.append({
                        "Page": current_url,
                        "Link": abs_url,
                        "Type": link_type,
                        "Status Code": code,
                        "Status": status_str
                    })

                    links_found += 1

                    # Queue internal links only
                    if is_internal and abs_url not in visited and abs_url not in to_visit:
                        to_visit.append(abs_url)

                # Optional: show live count
                if page_count % 5 == 0:
                    progress_bar.progress(min(page_count / max_pages, 0.98))

            except Exception as e:
                results.append({
                    "Page": current_url,
                    "Link": current_url,
                    "Type": "Page itself",
                    "Status Code": "Error",
                    "Status": f"Failed to crawl ({str(e)[:60]})"
                })

        progress_bar.progress(1.0)

    # ────────────────────────────────────────
    #               RESULTS
    # ────────────────────────────────────────

    end_time = time.time()
    duration = end_time - start_time

    if not results:
        st.warning("No links found or crawl failed completely.")
    else:
        df = pd.DataFrame(results)

        broken_df = df[df["Status"].str.contains("Broken|Error|Timeout", case=False, na=False)]
        redirect_df = df[df["Status"].str.contains("Redirect", na=False)]

        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Pages crawled", len(visited))
        col_b.metric("Broken links found", len(broken_df))
        col_c.metric("Redirects found", len(redirect_df))

        st.markdown(f"**Scan finished in {duration:.1f} seconds**")

        # Tabs for filtering
        tab1, tab2, tab3 = st.tabs(["All Links", "Broken Only", "Redirects"])

        with tab1:
            st.dataframe(
                df.sort_values(["Status", "Page"]),
                use_container_width=True,
                hide_index=True
            )

        with tab2:
            if broken_df.empty:
                st.success("No broken links found 🎉")
            else:
                st.dataframe(
                    broken_df.sort_values("Page"),
                    use_container_width=True,
                    hide_index=True
                )

        with tab3:
            if redirect_df.empty:
                st.info("No redirects found")
            else:
                st.dataframe(
                    redirect_df.sort_values("Page"),
                    use_container_width=True,
                    hide_index=True
                )

        # Export
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Download full report (CSV)",
            data=csv,
            file_name=f"broken_links_{urlparse(start_url).netloc}.csv",
            mime="text/csv"
        )

        st.caption("Tip: For large sites use sitemap.xml + this tool only on important pages.")
