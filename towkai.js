const mangayomiSources = [{
    "name": "Towkai",
    "lang": "en",
    "baseUrl": "http://mm.towkai.com",
    "apiUrl": "",
    "iconUrl": "http://mm.towkai.com/uploads/system_logo/logo_629599c462f85.png",
    "typeSource": "single",
    "itemType": 1,
    "isNsfw": false,
    "version": "1.0.0",
    "pkgPath": "towkai/default",
    "notes": ""
}];

class DefaultExtension extends MProvider {

    // -----------------------------
    // Helpers
    // -----------------------------

    cleanText(text) {
        if (!text) return "";

        return text
            .replace(/<[^>]*>/g, " ")
            .replace(/&nbsp;/gi, " ")
            .replace(/&amp;/gi, "&")
            .replace(/&quot;/gi, '"')
            .replace(/&#39;/gi, "'")
            .replace(/&#x27;/gi, "'")
            .replace(/&lt;/gi, "<")
            .replace(/&gt;/gi, ">")
            .replace(/\s+/g, " ")
            .trim();
    }

    absoluteUrl(url) {
        if (!url) return "";

        url = url.trim();

        if (url.startsWith("http://") || url.startsWith("https://")) {
            return url;
        }

        if (url.startsWith("//")) {
            return "http:" + url;
        }

        if (url.startsWith("/")) {
            return this.source.baseUrl + url;
        }

        return this.source.baseUrl + "/" + url;
    }

    extractCards(html) {
        const list = [];
        const blocks = html
            .split('class="latest-movie-img-container')
            .slice(1);

        const seen = {};

        for (const block of blocks) {

            let imageUrl = "";

            if (block.includes('data-src="')) {
                imageUrl = block
                    .substringAfter('data-src="')
                    .substringBefore('"')
                    .trim();
            }

            let url = "";

            const watchMatch = block.match(
                /href=["']([^"']*\/watch\/[^"']+)["']/i
            );

            if (watchMatch) {
                url = watchMatch[1].trim();
            }

            let name = "";

            if (block.includes('class="movie-title"')) {
                name = block
                    .substringAfter('class="movie-title"')
                    .substringAfter('<h3>')
                    .substringAfter('>')
                    .substringBefore('</a>')
                    .trim();
            }

            name = this.cleanText(name);
            url = this.absoluteUrl(url);

            if (!name || !url) {
                continue;
            }

            if (seen[url]) {
                continue;
            }

            seen[url] = true;

            list.push({
                "name": name,
                "url": url,
                "imageUrl": imageUrl
            });
        }

        return list;
    }

    extractSection(html, sectionId, nextSectionId) {
        const startMarker = 'id="' + sectionId + '"';
        const start = html.indexOf(startMarker);

        if (start === -1) {
            return "";
        }

        if (!nextSectionId) {
            return html.substring(start);
        }

        const endMarker = 'id="' + nextSectionId + '"';
        const end = html.indexOf(endMarker, start + startMarker.length);

        if (end === -1) {
            return html.substring(start);
        }

        return html.substring(start, end);
    }

    // -----------------------------
    // Home / Popular
    // -----------------------------

    async getPopular(page) {
        const client = new Client();

        const res = await client.get(this.source.baseUrl + "/");
        const html = res.body;

        // Towkai home has a Top Weekly movie section.
        let section = this.extractSection(
            html,
            "top-weekly",
            "top-rating"
        );

        // Fallback if the section marker changes.
        if (!section) {
            section = html;
        }

        const list = this.extractCards(section);

        return {
            "list": list,
            "hasNextPage": false
        };
    }

    // -----------------------------
    // Search
    // -----------------------------

    async search(query, page, filters) {
        const client = new Client();

        const searchUrl =
            this.source.baseUrl +
            "/search?q=" +
            encodeURIComponent(query);

        const res = await client.get(searchUrl);
        const html = res.body;

        const list = this.extractCards(html);

        return {
            "list": list,
            "hasNextPage": false
        };
    }

    // -----------------------------
    // Detail / Episodes
    // -----------------------------

    async getDetail(url) {
        const client = new Client();

        const res = await client.get(url);
        const html = res.body;

        // Title
        let title = "";

        const titleMatch = html.match(
            /<h1[^>]*>\s*([\s\S]*?)\s*<\/h1>/i
        );

        if (titleMatch) {
            title = this.cleanText(titleMatch[1]);
        }

        if (!title) {
            const ogTitle = html.match(
                /<meta\s+property=["']og:title["']\s+content=["']([^"']*)["']/i
            );

            if (ogTitle) {
                title = this.cleanText(ogTitle[1]);
            }
        }

        // Description
        let description = "";

        // First try meta description.
        const metaDesc = html.match(
            /<meta\s+name=["']description["']\s+content=["']([\s\S]*?)["']\s*\/?>/i
        );

        if (metaDesc) {
            description = this.cleanText(metaDesc[1]);
        }

        // Fallback to visible description.
        if (!description) {
            const h5Match = html.match(
                /<h5[^>]*>\s*<p[^>]*>\s*([\s\S]*?)\s*<\/p>\s*<\/h5>/i
            );

            if (h5Match) {
                description = this.cleanText(h5Match[1]);
            }
        }

        // Fallback to OpenGraph description.
        if (!description) {
            const ogDesc = html.match(
                /<meta\s+property=["']og:description["']\s+content=["']([\s\S]*?)["']\s*\/?>/i
            );

            if (ogDesc) {
                description = this.cleanText(ogDesc[1]);
            }
        }

        // Cover
        let coverImg = "";

        const ogImage = html.match(
            /<meta\s+property=["']og:image["']\s+content=["']([^"']+)["']/i
        );

        if (ogImage) {
            coverImg = ogImage[1].trim();
        }

        if (!coverImg) {
            const coverMatch = html.match(
                /class=["']col-md-3 m-t-10["'][\s\S]*?<img[^>]*src=["']([^"']+)["']/i
            );

            if (coverMatch) {
                coverImg = coverMatch[1].trim();
            }
        }

        if (!coverImg) {
            const thumbMatch = html.match(
                /<meta\s+name=["']twitter:image["']\s+content=["']([^"']+)["']/i
            );

            if (thumbMatch) {
                coverImg = thumbMatch[1].trim();
            }
        }

        // Episodes
        const chapters = [];

        const figureBlocks = html
            .split('<figure class="figure"')
            .slice(1);

        for (const block of figureBlocks) {

            let epUrl = "";

            const epUrlMatch = block.match(
                /<a\s+href=["']([^"']+)["']/i
            );

            if (epUrlMatch) {
                epUrl = this.absoluteUrl(epUrlMatch[1]);
            }

            let epName = "";

            const epNameMatch = block.match(
                /<figcaption[^>]*>\s*([\s\S]*?)\s*<\/figcaption>/i
            );

            if (epNameMatch) {
                epName = this.cleanText(epNameMatch[1]);
            }

            if (epUrl && epName) {
                chapters.push({
                    "name": epName,
                    "url": epUrl
                });
            }
        }

        // Movie: no <figure>, so create one playable chapter.
        if (chapters.length === 0) {
            chapters.push({
                "name": title || "Movie",
                "url": url
            });
        }

        return {
            "name": title,
            "description": description,
            "imageUrl": coverImg,
            "status": 1,
            "chapters": chapters
        };
    }

    // -----------------------------
    // Video URL
    // -----------------------------

    async getVideoList(url) {
        const client = new Client();

        const res = await client.get(url);
        const html = res.body;

        const videos = [];
        const seen = {};

        // Normal Towkai player format:
        // sources: [{
        //     src: 'VIDEO_URL',
        //     type: 'application/x-mpegURL'
        // }]
        const sourceRegex =
            /sources\s*:\s*\[\s*\{\s*src\s*:\s*['"]([^'"]+)['"]/gi;

        let match;

        while ((match = sourceRegex.exec(html)) !== null) {
            const videoUrl = match[1].trim();

            if (!videoUrl || seen[videoUrl]) {
                continue;
            }

            seen[videoUrl] = true;

            videos.push({
                "url": videoUrl,
                "originalUrl": videoUrl,
                "quality": "Auto"
            });
        }

        // Fallback: find any m3u8 URL directly in the page.
        if (videos.length === 0) {
            const m3u8Regex =
                /['"]([^'"]+\.m3u8(?:\?[^'"]*)?)['"]/gi;

            while ((match = m3u8Regex.exec(html)) !== null) {
                const videoUrl = match[1].trim();

                if (!videoUrl || seen[videoUrl]) {
                    continue;
                }

                seen[videoUrl] = true;

                videos.push({
                    "url": videoUrl,
                    "originalUrl": videoUrl,
                    "quality": "Auto"
                });
            }
        }

        return videos;
    }

    // -----------------------------
    // Latest
    // -----------------------------

    get supportsLatest() {
        return true;
    }

    async getLatestUpdates(page) {
        const client = new Client();

        const res = await client.get(this.source.baseUrl + "/");
        const html = res.body;

        let section = this.extractSection(
            html,
            "recently-added",
            "recently-released"
        );

        if (!section) {
            section = html;
        }

        const list = this.extractCards(section);

        return {
            "list": list,
            "hasNextPage": false
        };
    }

    // -----------------------------
    // Other required methods
    // -----------------------------

    getHeaders() {
        return {};
    }

    async getHtmlContent(url) {
        return "";
    }

    async cleanHtmlContent(html) {
        return html;
    }

    async getPageList(url) {
        return [];
    }

    getFilterList() {
        return [];
    }

    getSourcePreferences() {
        return [];
    }
}
