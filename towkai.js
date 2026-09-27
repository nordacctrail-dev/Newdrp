const mangayomiSources = [{
    "name": "Towkai",
    "lang": "en",
    "baseUrl": "http://mm.towkai.com",
    "apiUrl": "",
    "iconUrl": "http://mm.towkai.com/uploads/system_logo/logo_629599c462f85.png",
    "typeSource": "single",
    "itemType": 1,
    "isManga": false,
    "isNsfw": false,
    "version": "0.0.7",
    "pkgPath": "towkai/default",
    "notes": ""
}];

class DefaultExtension extends MProvider {

    async getPopular(page) {

        const client = new Client();

        const res = await client.get(
            this.source.baseUrl +
            "/movies_details.html?sort=top"
        );

        const html = res.body;

        const list = [];

        const blocks =
            html
                .split('class="latest-movie-img-container')
                .slice(1);

        for (const block of blocks) {

            let img =
                block
                    .substringAfter('data-src="')
                    .substringBefore('"')
                    .trim();

            let url =
                block
                    .substringAfter('<a href="')
                    .substringBefore('"')
                    .trim();

            let name =
                block
                    .substringAfter('class="movie-title"')
                    .substringAfter("<h3>")
                    .substringAfter(">")
                    .substringBefore("</a>")
                    .trim();

            list.push({
                "name": name,
                "url": url,
                "link": url,
                "imageUrl": img
            });
        }

        return {
            "list": list,
            "hasNextPage": false
        };
    }


    async search(query, page, filters) {

        const client = new Client();

        const res = await client.get(
            this.source.baseUrl +
            "/search?q=" +
            encodeURIComponent(query)
        );

        const html = res.body;

        const list = [];

        const blocks =
            html
                .split('class="latest-movie-img-container')
                .slice(1);

        for (const block of blocks) {

            let img =
                block
                    .substringAfter('data-src="')
                    .substringBefore('"')
                    .trim();

            let url =
                block
                    .substringAfter('<a href="')
                    .substringBefore('"')
                    .trim();

            let name =
                block
                    .substringAfter('class="movie-title"')
                    .substringAfter("<h3>")
                    .substringAfter(">")
                    .substringBefore("</a>")
                    .trim();

            list.push({
                "name": name,
                "url": url,
                "link": url,
                "imageUrl": img
            });
        }

        return {
            "list": list,
            "hasNextPage": false
        };
    }


    async getDetail(url) {

        const client = new Client();

        const res =
            await client.get(url);

        const html =
            res.body;

        // TITLE
        let title =
            html
                .substringAfter("<title>")
                .substringBefore("</title>")
                .trim();


        // DESCRIPTION
        let description = "";

        if (
            html.includes(
                '<meta name="description"'
            )
        ) {

            description =
                html
                    .substringAfter(
                        '<meta name="description"'
                    )
                    .substringAfter('content="')
                    .substringBefore('"')
                    .trim();
        }


        // IMAGE
        let image =
            html
                .substringAfter(
                    'property="og:image"'
                )
                .substringAfter('content="')
                .substringBefore('"')
                .trim();


        // EPISODES
        const episodes = [];

        const blocks =
            html
                .split('figure class="figure"')
                .slice(1);

        for (const block of blocks) {

            let episodeUrl =
                block
                    .substringAfter('<a href="')
                    .substringBefore('"')
                    .trim();

            let episodeName = "";

            if (
                block.includes("<figcaption")
            ) {

                episodeName =
                    block
                        .substringAfter("<figcaption")
                        .substringAfter(">")

                        // IMPORTANT
                        .substringBefore("</figcaption")

                        .trim();
            }

            if (!episodeName) {

                episodeName =
                    block
                        .substringAfter('alt="')
                        .substringBefore('"')
                        .trim();
            }

            if (episodeUrl) {

                episodes.push({
                    "name":
                        episodeName,

                    "url":
                        episodeUrl
                });
            }
        }


        // Towkai HTML is oldest -> newest.
        // Mangayomi normally shows newest first.
        episodes.reverse();


        // MOVIE
        if (episodes.length === 0) {

            episodes.push({
                "name": "Movie",
                "url": url
            });
        }


        return {
            "title": title,
            "description": description,
            "author": "",
            "genre": [],
            "status": 1,
            "imageUrl": image,
            "episodes": episodes
        };
    }


    async getVideoList(url) {

        const client =
            new Client();

        const res =
            await client.get(url);

        const html =
            res.body;

        let videoUrl = "";


        // EXACT TOWKAI FORMAT
        if (
            html.includes("sources: [{")
        ) {

            videoUrl =
                html
                    .substringAfter(
                        "sources: [{"
                    )
                    .substringAfter("src: '")
                    .substringBefore("'")
                    .trim();
        }


        // FALLBACK
        if (
            !videoUrl &&
            html.includes("src: '")
        ) {

            const parts =
                html.split("src: '");

            for (
                let i = 1;
                i < parts.length;
                i++
            ) {

                let candidate =
                    parts[i]
                        .substringBefore("'")
                        .trim();

                if (
                    candidate.includes(".m3u8")
                ) {

                    videoUrl =
                        candidate;

                    break;
                }
            }
        }


        if (!videoUrl) {
            return [];
        }


        return [{
            "url": videoUrl,
            "originalUrl": videoUrl,
            "quality": "Auto"
        }];
    }


    getHeaders() {
        return {};
    }


    get supportsLatest() {
        return true;
    }


    async getLatestUpdates(page) {

        const client =
            new Client();

        const res =
            await client.get(
                this.source.baseUrl +
                "/movies_details.html?sort=added"
            );

        const html =
            res.body;

        const list = [];

        const blocks =
            html
                .split('class="latest-movie-img-container')
                .slice(1);

        for (const block of blocks) {

            let img =
                block
                    .substringAfter('data-src="')
                    .substringBefore('"')
                    .trim();

            let url =
                block
                    .substringAfter('<a href="')
                    .substringBefore('"')
                    .trim();

            let name =
                block
                    .substringAfter('class="movie-title"')
                    .substringAfter("<h3>")
                    .substringAfter(">")
                    .substringBefore("</a>")
                    .trim();

            list.push({
                "name": name,
                "url": url,
                "link": url,
                "imageUrl": img
            });
        }

        return {
            "list": list,
            "hasNextPage": false
        };
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
