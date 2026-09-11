"""Select usable page evidence consistently across content-analysis skills."""


def effective_pages(store):
    observations = store.get("observations", [])
    fetches = {o["source_url"]: o for o in observations if o["type"] == "HTTP_FETCH"}
    renders = {o["source_url"]: o for o in observations if o["type"] == "RENDER"}
    pages = {}
    for url, fetch in fetches.items():
        render = renders.get(url)
        selected = None
        if render and render["value"].get("status") == "ok" and 200 <= (render["value"].get("status_code") or 0) < 300 and render["value"].get("html"):
            selected = render
        elif 200 <= (fetch["value"].get("status_code") or 0) < 300 and fetch["value"].get("html"):
            selected = fetch
        if selected:
            pages[url] = {"html": selected["value"]["html"], "observation_id": selected["id"],
                          "headers": fetch["value"].get("headers", {}), "rendered": selected is render}
            if selected is render and 'measurements' in selected['value']:
                pages[url]['measurements'] = selected['value']['measurements']
    return pages
