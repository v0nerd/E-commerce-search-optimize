import streamlit as st
import requests
import json
from diff_match_patch import diff_match_patch
from urllib.parse import urlparse, urlunparse
import pandas as pd
import plotly.express as px
import plotly.graph_objs as go
import time

# Initialize session state variables
if 'vis_type' not in st.session_state:
    st.session_state.vis_type = "Stacked Line Chart"
if 'show_results' not in st.session_state:
    st.session_state.show_results = False
if 'unique_urls' not in st.session_state:
    st.session_state.unique_urls = []
if 'domain' not in st.session_state:
    st.session_state.domain = ""
if 'active_tab' not in st.session_state:
    st.session_state.active_tab = "Folder Visualisation"
if 'top_folders_count' not in st.session_state:
    st.session_state.top_folders_count = 10
if 'frequently_changed_pages' not in st.session_state:
    st.session_state.frequently_changed_pages = []


def clean_url(url):
    parsed = urlparse(url)
    netloc = parsed.netloc.split('@')[-1].split(':')[0]
    clean = urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))
    return clean


def get_unique_urls(domain):
    domain = domain.replace('http://', '').replace('https://', '').rstrip('/')
    base_url = f"http://web.archive.org/cdx/search/cdx"
    params = {
        "url": f"{domain}/*",
        "output": "json",
        "fl": "original,timestamp,statuscode,digest",
        "pageSize": 50000,
        "showNumPages": "true"
    }

    response = requests.get(base_url, params=params, timeout=60)
    if response.status_code != 200:
        st.error(f"Error: Unable to fetch data. Status code: {response.status_code}")
        return []

    try:
        data = json.loads(response.text)
        num_pages = len(data) - 1
    except json.JSONDecodeError:
        st.error("Error: Unable to parse the response from the server.")
        return []

    if num_pages == 0:
        st.warning("No pages found for the given domain.")
        return []

    st.info(f"Total pages to process: {num_pages}")

    unique_urls = []
    for page in range(num_pages):
        params["page"] = page
        params.pop("showNumPages", None)

        try:
            response = requests.get(base_url, params=params, timeout=60)
            response.raise_for_status()
            data = response.json()

            for item in data[1:]:
                url = clean_url(item[0])
                timestamp = item[1]
                statuscode = item[2]
                digest = item[3]
                unique_urls.append((url, timestamp, statuscode, digest))

            st.progress((page + 1) / num_pages)
            time.sleep(1)
        except requests.exceptions.RequestException as e:
            st.warning(f"Error fetching page {page}: {str(e)}")
            time.sleep(5)

    return unique_urls


def get_top_folder(url):
    parsed = urlparse(url)
    path = parsed.path.strip('/')
    if not path:
        return "Root"
    top_folder = path.split('/')[0]
    return f"/{top_folder}/"


def visualize_folder_types_over_time(urls, chart_type):
    df = pd.DataFrame(urls, columns=['url', 'timestamp', 'statuscode', 'digest'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], format='%Y%m%d%H%M%S')
    df['year'] = df['timestamp'].dt.year.astype(str)
    df['folder'] = df['url'].apply(get_top_folder)

    df_grouped = df.groupby(['year', 'folder']).size().unstack(fill_value=0)
    df_grouped = df_grouped.sort_index()
    folder_totals = df_grouped.sum().sort_values(ascending=False)
    df_grouped = df_grouped[folder_totals.index]

    top_folders = folder_totals.nlargest(st.session_state.top_folders_count).index
    df_grouped['Other'] = df_grouped.loc[:, ~df_grouped.columns.isin(top_folders)].sum(axis=1)
    df_grouped = df_grouped[list(top_folders) + ['Other']]

    if chart_type == "Stacked Bar Chart":
        fig = px.bar(df_grouped, x=df_grouped.index, y=df_grouped.columns,
                     title="Evolution of Website Structure Over Time",
                     labels={'value': 'Number of URLs', 'year': 'Year'},
                     category_orders={"year": sorted(df_grouped.index)},
                     )
        fig.update_layout(legend_title_text='Folders', barmode='stack')
    else:  # Stacked Line Chart
        fig = go.Figure()
        for folder in df_grouped.columns:
            fig.add_trace(go.Scatter(
                x=df_grouped.index,
                y=df_grouped[folder],
                mode='lines',
                stackgroup='one',
                name=folder
            ))
        fig.update_layout(
            title="Evolution of Website Structure Over Time",
            xaxis_title="Year",
            yaxis_title="Number of URLs",
            legend_title_text='Folders'
        )

    fig.update_xaxes(title_text="Year", type='category')
    fig.update_yaxes(title_text="Number of URLs")
    return fig


def group_status_code(code):
    try:
        code = int(code)
        if code < 200:
            return '1xx'
        elif code < 300:
            return '2xx'
        elif code < 400:
            return '3xx'
        elif code < 500:
            return '4xx'
        else:
            return '5xx'
    except ValueError:
        return 'Unknown'

def visualize_status_codes_over_time(urls, chart_type):
    df = pd.DataFrame(urls, columns=['url', 'timestamp', 'statuscode', 'digest'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], format='%Y%m%d%H%M%S')
    df['year'] = df['timestamp'].dt.year.astype(str)

    df['status_group'] = df['statuscode'].apply(group_status_code)
    df_grouped = df.groupby(['year', 'status_group']).size().unstack(fill_value=0)
    df_grouped = df_grouped.sort_index()

    # Ensure all status groups are present
    all_status_groups = ['1xx', '2xx', '3xx', '4xx', '5xx', 'Unknown']
    for group in all_status_groups:
        if group not in df_grouped.columns:
            df_grouped[group] = 0

    if chart_type == "Stacked Bar Chart":
        fig = px.bar(df_grouped, x=df_grouped.index, y=all_status_groups,
                     title="Evolution of Status Codes Over Time",
                     labels={'value': 'Number of URLs', 'year': 'Year'},
                     category_orders={"year": sorted(df_grouped.index)},
                     )
        fig.update_layout(legend_title_text='Status Codes', barmode='stack')
    else:  # Stacked Line Chart
        fig = go.Figure()
        for status_group in all_status_groups:
            fig.add_trace(go.Scatter(
                x=df_grouped.index,
                y=df_grouped[status_group],
                mode='lines',
                stackgroup='one',
                name=status_group
            ))
        fig.update_layout(
            title="Evolution of Status Codes Over Time",
            xaxis_title="Year",
            yaxis_title="Number of URLs",
            legend_title_text='Status Codes'
        )

    fig.update_xaxes(title_text="Year", type='category')
    fig.update_yaxes(title_text="Number of URLs")
    return fig

def fetch_robots_txt_data(domain):
    domain = domain.replace('http://', '').replace('https://', '').rstrip('/')
    base_url = f"http://web.archive.org/cdx/search/cdx"
    params = {
        "url": f"{domain}/robots.txt",
        "output": "json",
        "fl": "timestamp,statuscode,digest,original",
        "filter": "statuscode:200",
        "collapse": "digest",
        "sort": "timestamp"
    }

    response = requests.get(base_url, params=params, timeout=60)
    if response.status_code != 200:
        st.error(f"Error: Unable to fetch robots.txt data. Status code: {response.status_code}")
        return []

    try:
        data = json.loads(response.text)
        return data[1:]  # Skip the header row
    except json.JSONDecodeError:
        st.error("Error: Unable to parse the response from the server.")
        return []


def process_robots_txt_changes(robots_txt_data):
    changes = {}
    for item in robots_txt_data:
        if len(item) == 4:
            timestamp, statuscode, digest, original = item
        elif len(item) == 3:
            timestamp, statuscode, digest = item
            original = None

        if digest not in changes:
            changes[digest] = (timestamp, digest, original)

    return sorted(changes.values(), key=lambda x: x[0])  # Sort by timestamp


def compare_robots_txt(domain, old_version, new_version):
    old_content = fetch_robots_txt_content(domain, old_version[0])
    new_content = fetch_robots_txt_content(domain, new_version[0])

    if old_content is None or new_content is None:
        return "Error: Unable to fetch one or both versions of robots.txt"

    dmp = diff_match_patch()
    diffs = dmp.diff_main(old_content, new_content)
    dmp.diff_cleanupSemantic(diffs)

    return diffs

def visualize_robots_txt_changes(changes):
    df = pd.DataFrame(changes, columns=['timestamp', 'digest', 'content'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], format='%Y%m%d%H%M%S')
    df = df.sort_values('timestamp')

    fig = go.Figure()

    # Add a dotted line for the entire time range
    fig.add_trace(go.Scatter(
        x=[df['timestamp'].min(), df['timestamp'].max()],
        y=[0, 0],
        mode='lines',
        line=dict(color='gray', dash='dot'),
        showlegend=False
    ))

    # Add vertical dotted lines for each change
    for ts in df['timestamp']:
        fig.add_shape(
            type="line",
            x0=ts, x1=ts, y0=-0.1, y1=0.1,
            line=dict(color="gray", width=1, dash="dot"),
        )

    # Add markers for each change
    fig.add_trace(go.Scatter(
        x=df['timestamp'],
        y=[0] * len(df),
        mode='markers',
        marker=dict(
            size=10,
            color='blue',
            symbol='circle'
        ),
        text=[f"Changed at {ts:%Y-%m-%d %H:%M:%S}" for ts in df['timestamp']],
        hoverinfo='text',
        name='Changes'
    ))

    # Customize the layout
    fig.update_layout(
        title="Timeline of Unique robots.txt Changes",
        xaxis_title="Date",
        yaxis_visible=False,
        height=400,
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor="rgba(255, 255, 255, 0.8)",
            font_size=12,
            font_color="black",
        ),
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
    )

    # Set x-axis range to show a bit before the first change and after the last change
    date_range = df['timestamp'].max() - df['timestamp'].min()
    fig.update_xaxes(
        range=[
            df['timestamp'].min() - date_range * 0.05,
            df['timestamp'].max() + date_range * 0.05
        ],
        tickformat='%Y-%m-%d',
        gridcolor='rgba(128,128,128,0.1)',
        linecolor='rgba(128,128,128,0.2)',
    )

    fig.update_yaxes(
        gridcolor='rgba(128,128,128,0.1)',
        linecolor='rgba(128,128,128,0.2)',
    )

    return fig

# New function to get top changing folders
def get_top_changing_pages(urls, top_n=10):
    page_changes = {}
    for url, _, _, digest in urls:
        if url not in page_changes:
            page_changes[url] = set()
        page_changes[url].add(digest)

    page_change_counts = {url: len(changes) for url, changes in page_changes.items()}
    sorted_pages = sorted(page_change_counts.items(), key=lambda x: x[1], reverse=True)
    return sorted_pages[:top_n]


# New function to visualize top changing folders
def visualize_top_changing_pages(top_changing_pages, chart_type):
    df = pd.DataFrame(top_changing_pages, columns=['page', 'changes'])
    df = df.sort_values('changes', ascending=True)

    if chart_type == "Stacked Bar Chart":
        fig = px.bar(df, x='changes', y='page', orientation='h',
                     title="Top Frequently Changing Pages",
                     labels={'changes': 'Number of Changes', 'page': 'Page'})
    else:  # Stacked Line Chart (we'll use a horizontal bar chart here as well)
        fig = go.Figure(go.Bar(
            x=df['changes'],
            y=df['page'],
            orientation='h'
        ))
        fig.update_layout(
            title="Top Frequently Changing Pages",
            xaxis_title="Number of Changes",
            yaxis_title="Page"
        )

    fig.update_layout(height=600, width=800)
    fig.update_xaxes(title_text="Number of Changes")
    fig.update_yaxes(title_text="Page")
    return fig


def update_vis_type():
    st.session_state.vis_type = st.session_state.vis_type_radio

def on_tab_change():
    st.session_state.active_tab = st.session_state.tab_selector

def fetch_urls():
    if st.session_state.domain:
        with st.spinner("Fetching URLs... This may take a while for large websites."):
            unique_urls = get_unique_urls(st.session_state.domain)

        if unique_urls:
            st.success(f"Found {len(unique_urls)} URLs.")
            st.session_state.unique_urls = unique_urls
            st.session_state.show_results = True
        else:
            st.warning("No URLs found. Check the domain name.")
    else:
        st.warning("Please enter a domain.")


st.set_page_config(page_title="Internet Archive Analyser", page_icon="🕸️", layout="wide")

# Sidebar content
st.sidebar.image(
    "https://upload.wikimedia.org/wikipedia/commons/thumb/0/01/Wayback_Machine_logo_2010.svg/1200px-Wayback_Machine_logo_2010.svg.png",
    width=200)

st.sidebar.markdown("---")

st.sidebar.subheader("Visualisation Options")

# Move Visualisation type selection to sidebar
st.sidebar.radio(
    "Select Visualisation type:",
    ["Stacked Line Chart", "Stacked Bar Chart"],
    key="vis_type_radio",
    on_change=update_vis_type,
    index=["Stacked Line Chart", "Stacked Bar Chart"].index(st.session_state.vis_type)
)

# Add slider for top folders count in sidebar
st.session_state.top_folders_count = st.sidebar.slider(
    "Number of top folders to display",
    min_value=5,
    max_value=50,
    value=st.session_state.top_folders_count,
    step=1
)

st.sidebar.markdown("---")

st.sidebar.subheader("About")
st.sidebar.info("""
    This app leverages the Wayback Machine's CDX server to analyze and visualise the historical evolution of websites.

    1. URL Retrieval: Fetches all archived URLs for a given domain from the Internet Archive.
    2. Folder Structure Visualisation: Displays how the website's folder structure has changed over time.
    3. Status Code Analysis: Shows the distribution of HTTP status codes across the site's history.
    4. Frequently Changed Pages: Identifies and lists the pages that have been modified most often.
    5. robots.txt Evolution: Tracks and visualises changes to the site's robots.txt file over time.
    6. Rover from Failed Migrations
""")

# Main content
st.title("🕸️ Wayback Machine URL Fetcher")

st.write("Fetch and filter URLs from the Wayback Machine for any domain.")

def handle_submit():
    if st.session_state.domain:
        fetch_urls()
    else:
        st.warning("Please enter a domain.")

# Input form
with st.form(key='url_form'):
    st.session_state.domain = st.text_input(
        "Enter a domain (e.g., example.com):",
        help="You can enter the domain with or without 'http://' or 'https://'",
        value=st.session_state.domain
    )
    submit_button = st.form_submit_button(label='Fetch URLs')

if submit_button:
    handle_submit()

def fetch_robots_txt_content(domain, timestamp):
    url = f"https://web.archive.org/web/{timestamp}id_/{domain}/robots.txt"
    response = requests.get(url, timeout=60)
    if response.status_code == 200:
        return response.text
    else:
        return None


# Display results after form submission
if st.session_state.show_results:
    # Create tabs
    tab_names = ["Folder Visualisation", "Status Code Visualisation", "Frequently Changed Pages", "robots.txt Changes",
                 "Download URLs"]

    # Use a single selectbox to choose the active tab
    selected_tab = st.selectbox("Select a tab:", tab_names, key="tab_selector", on_change=on_tab_change,
                                index=tab_names.index(st.session_state.active_tab))

    # Update active_tab based on selection
    if selected_tab != st.session_state.active_tab:
        st.session_state.active_tab = selected_tab

    # Display content based on the selected tab
    if st.session_state.active_tab == "Folder Visualisation":
        st.header("Folder Visualisation")
        st.plotly_chart(visualize_folder_types_over_time(st.session_state.unique_urls, st.session_state.vis_type),
                        use_container_width=True)

    elif st.session_state.active_tab == "Status Code Visualisation":
        st.header("Status Code Visualisation")
        st.plotly_chart(visualize_status_codes_over_time(st.session_state.unique_urls, st.session_state.vis_type),
                        use_container_width=True)

    elif st.session_state.active_tab == "Frequently Changed Pages":
        # st.header("Frequently Changed Pages")

        top_changing_pages = get_top_changing_pages(st.session_state.unique_urls,
                                                    top_n=st.session_state.top_folders_count)

        # Visualisation
        st.subheader(f"Top {st.session_state.top_folders_count} Frequently Changing Pages")
        st.plotly_chart(visualize_top_changing_pages(top_changing_pages, st.session_state.vis_type),
                        use_container_width=True)

        # Dropdown menu
        selected_page = st.selectbox(
            "Select a frequently changing page:",
            options=[f"{page} ({changes})" for page, changes in top_changing_pages],
            format_func=lambda x: x
        )

        if selected_page:
            page = selected_page.split(" (")[0]
            page_urls = [item for item in st.session_state.unique_urls if item[0] == page]
            page_urls.sort(key=lambda x: x[1], reverse=True)  # Sort by timestamp, most recent first

            st.subheader(f"Change History for {page}")
            for i, (url, timestamp, statuscode, digest) in enumerate(page_urls[:50]):  # Show top 50 changes
                with st.expander(f"{timestamp}"):
                    col1, col2, col3 = st.columns([2, 1, 1])
                    with col1:
                        st.write(f"URL: {url}")
                    with col2:
                        st.write(f"Status: {statuscode}")
                    with col3:
                        wayback_url = f"https://web.archive.org/web/{timestamp}/{url}"
                        st.markdown(f"[View Version]({wayback_url})")
                    st.write(f"Digest: {digest}")

            st.write("Note: Showing up to 50 most recent changes per page.")

    elif st.session_state.active_tab == "robots.txt Changes":
        st.header("robots.txt Changes")

        robots_txt_data = fetch_robots_txt_data(st.session_state.domain)
        if robots_txt_data:
            changes = process_robots_txt_changes(robots_txt_data)
            if changes:
                fig = visualize_robots_txt_changes(changes)
                st.plotly_chart(fig, use_container_width=True)

                st.subheader("Compare unique robots.txt versions")
                col1, col2 = st.columns(2)
                with col1:
                    date1 = st.selectbox("Select first version", options=changes,
                                         format_func=lambda x: pd.to_datetime(x[0], format='%Y%m%d%H%M%S'), key="date1")
                with col2:
                    date2 = st.selectbox("Select second version", options=changes,
                                         format_func=lambda x: pd.to_datetime(x[0], format='%Y%m%d%H%M%S'), index=1,
                                         key="date2")

                if st.button("Compare versions"):
                    with st.spinner("Fetching and comparing robots.txt versions..."):
                        diffs = compare_robots_txt(st.session_state.domain, date1, date2)

                    # Display the full content of both versions
                    st.subheader("Full content of selected versions")
                    col1, col2 = st.columns(2)
                    with col1:
                        st.text(f"Version from {pd.to_datetime(date1[0], format='%Y%m%d%H%M%S')}")
                        content1 = fetch_robots_txt_content(st.session_state.domain, date1[0])
                        st.code(content1, language="text")
                    with col2:
                        st.text(f"Version from {pd.to_datetime(date2[0], format='%Y%m%d%H%M%S')}")
                        content2 = fetch_robots_txt_content(st.session_state.domain, date2[0])
                        st.code(content2, language="text")

    elif st.session_state.active_tab == "Download URLs":
        st.header("Download URLs")

        # Add filter options here
        filter_option = st.radio(
            "Select URL filter option:",
            ["All (HTML, Images, CSS, JS, etc.)", "HTML only", "HTML + Images"],
            index=0,
            help="Choose which types of URLs to include in the download. 'HTML only' includes HTML files and robots.txt, but excludes .json, .xml, and other .txt files."
        )

        unique_only = st.checkbox("Export only unique URLs", value=False,
                                  help="If checked, only one instance of each URL will be exported, regardless of how many times it was captured.")


        # Function to apply filter
        def apply_filter(url, option):
            if option == "All (HTML, Images, CSS, JS, etc.)":
                return True
            elif option == "HTML only":
                return url.endswith(('.html', '.htm', '/')) or url.endswith('robots.txt')
            elif option == "HTML + Images":
                return url.endswith(('.html', '.htm', '/', '.jpg', '.jpeg', '.png', '.gif', '.svg')) or url.endswith(
                    'robots.txt')


        # Filter URLs based on selected option
        filtered_urls = [url for url in st.session_state.unique_urls if apply_filter(url[0], filter_option)]

        # If unique_only is checked, keep only unique URLs
        if unique_only:
            unique_urls = {}
            for url, timestamp, statuscode, digest in filtered_urls:
                if url not in unique_urls:
                    unique_urls[url] = (url, timestamp, statuscode, digest)
            filtered_urls = list(unique_urls.values())

        # Prepare CSV content with headers
        csv_content = "URL,Timestamp,Status Code,Digest\n"
        csv_content += "\n".join(
            [f"{url},{timestamp},{statuscode},{digest}" for url, timestamp, statuscode, digest in filtered_urls])

        # Convert to bytes with UTF-8-SIG encoding (UTF-8 with BOM)
        csv_bytes = csv_content.encode('utf-8-sig')

        st.download_button(
            label="Download Filtered URLs",
            data=csv_bytes,
            file_name=f"{st.session_state.domain}_filtered_urls.csv",
            mime="text/csv",
            key="download"
        )

        st.write(f"Total URLs after filtering: {len(filtered_urls)}")
