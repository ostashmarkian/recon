"""The site's own API without a browser: API bases in runtime configs, bundles, routes, helpers, hosts."""

import json

import pytest
from fakes import BUNDLES, NUXT_CONFIG

from recon.api import (
    all_private,
    api_bases,
    builds_of,
    bundle_refs,
    chunk_refs,
    domain_of,
    failed,
    fill_for,
    helpers_in,
    internal_name,
    lists_to_ask,
    message_of,
    names_api,
    route_kind,
    routes_in,
    same_domain,
    stateful,
    wanted,
)


def test_nuxt_3_runtime_config() -> None:
    bases = api_bases(f"<html><body>{NUXT_CONFIG}</body></html>")
    assert bases == [
        {"url": "https://api.shop.test", "keys": ["apiHost", "API_HOST"], "source": "the Nuxt runtime config"},
        {
            "url": "http://api-noauth.backend.test",
            "keys": ["serverApiHost", "SERVER_API_HOST"],
            "source": "the Nuxt runtime config",
        },
    ], "baseURL: '/' and cdnURL are no API"


def test_nuxt_2_next_and_plain_scripts() -> None:
    nuxt2 = (
        '<script>window.__NUXT__=(function(a){return {config:{apiURL:"https:\\u002F\\u002Fapi.two.test\\u002Fv1"}}}'
        "(1))</script>"
    )
    assert api_bases(nuxt2) == [{"url": "https://api.two.test/v1", "keys": ["apiURL"], "source": "the Nuxt state"}]
    next_data = json.dumps({"runtimeConfig": {"graphqlEndpoint": "https://gql.three.test/graphql"}, "props": {}})
    found = api_bases(f'<script id="__NEXT_DATA__" type="application/json">{next_data}</script>')
    assert found == [
        {"url": "https://gql.three.test/graphql", "keys": ["graphqlEndpoint"], "source": "Next.js __NEXT_DATA__"}
    ]
    plain = (
        '<script>window.API_URL = "//api.four.test/"; var gtag = {apiUrl: "https://www.googletagmanager.com/x"};'
        ' const logo = {apiImage: "https://img.four.test/logo.png"}; const home = {link: "https://four.test/"}</script>'
        '<script src="/x.js" data-api="https://no.test"></script>'
    )
    assert api_bases(plain) == [{"url": "https://api.four.test", "keys": ["API_URL"], "source": "an inline script"}], (
        "a tracker, an image, a key that names no API and a script's file are left out"
    )


def test_the_bundles_a_page_loads() -> None:
    html = (
        '<link rel="modulepreload" as="script" crossorigin href="/_nuxt/a.js">'
        '<link rel="stylesheet" href="/_nuxt/a.css"><link rel="preload" as="script" href="/js/b.js?v=2">'
        '<link rel="preload" as="font" href="/f.woff2">'
        '<script type="module" src="/_nuxt/entry.js" crossorigin></script>'
        '<script src="https://cdn.other.test/lib.js"></script><script>inline()</script>'
    )
    assert bundle_refs(html, "https://shop.test/p/1") == [
        "https://shop.test/_nuxt/entry.js",
        "https://cdn.other.test/lib.js",
        "https://shop.test/_nuxt/a.js",
        "https://shop.test/js/b.js?v=2",
    ], "<script src> first, then the preloads of scripts; whose host it is the run decides"


def test_the_chunks_a_bundle_names() -> None:
    entry = "https://shop.test/_nuxt/entry.Cq2k.js"
    assert chunk_refs(BUNDLES["entry.Cq2k.js"], entry) == [
        "https://shop.test/_nuxt/Dk3list.js",
        "https://shop.test/_nuxt/Ab4detail.js",
    ]
    assert chunk_refs('import("../chunks/x.js");"vue.js"', "https://shop.test/assets/a/b.js") == [
        "https://shop.test/assets/chunks/x.js"
    ], "a bare name is no chunk"


def test_routes_and_their_methods() -> None:
    js = (
        BUNDLES["Bx1api.js"]
        + 'export const a=t=>http.post("/api/v2/search",t);'
        + 'const b=e=>$fetch(`/api/product/${e.id}/offers`,{method:"POST"});'
        + 'const c=()=>useFetch("/api/cart-count");'
        + 'fetch("/ajax/listing?page=2");'
        + 'const d={path:"/products/:id",url:"/products/usb"};const e="/api/img/logo.png";'
        + 'cache.get("/x");'
    )
    found = {r["route"]: r["method"] for r in routes_in(js)}
    assert found == {
        "/www-api/search/cate-search/get-search-result-v2": "GET",
        "/www-api/goods/spu-detail": "GET",
        "/www-api/goods/stock-info": "POST",
        "/www-api/cart/add": "POST",
        "/catalog-api/nav-cate/get-cate-list": "GET",
        "/api/v2/search": "POST",
        "/api/product/{}/offers": "POST",
        "/api/cart-count": "GET",
        "/ajax/listing?page=2": "GET",
    }, "a menu's url, a router's path, an image and a one-segment address are no routes"


@pytest.mark.parametrize(
    ("route", "kind"),
    [
        ("/www-api/search/cate-search/get-search-result-v2", "lists and search"),
        ("/catalog-api/nav-cate/get-cate-list", "lists and search"),
        ("/www-api/goods/spu-detail", "detail"),
        ("/api/product/get-availabilities", "stock and price"),
        ("/api/cookies-consent/get-all", "other"),
    ],
)
def test_what_a_route_is_for(route: str, kind: str) -> None:
    assert route_kind(route) == kind


def test_the_route_asked_without_the_browser() -> None:
    routes = [
        {"route": r, "method": m, "kind": route_kind(r)}
        for r, m in (
            ("/www-api/cart/add", "POST"),
            ("/catalog-api/nav-cate/get-cate-list", "GET"),
            ("/api/product/{}/list", "GET"),
            ("/www-api/search/get-search-result", "GET"),
            ("/api/search/x", "POST"),
        )
    ]
    assert [r["route"] for r in lists_to_ask(routes)] == [
        "/www-api/search/get-search-result",
        "/catalog-api/nav-cate/get-cate-list",
    ], "a route to fill in and a POST are never asked"


def test_a_helper_that_adds_parameters() -> None:
    assert helpers_in(BUNDLES["Bx1api.js"]) == [{"name": "addAntiSpiderParams", "sets": ["v", "v_", "p"]}]
    arrow = 'const signParams=(t)=>{t["sign"]=md5(t);t.ts=Date.now();return t};'
    assert helpers_in(arrow) == [{"name": "signParams", "sets": ["sign", "ts"]}]
    assert helpers_in("x.antiCrawlToken;") == [{"name": "antiCrawlToken", "sets": []}], "named, its body unseen"
    assert helpers_in("var assignment = 1;") == []


def test_which_hosts_are_internal() -> None:
    for host in ("localhost", "api", "api.svc.cluster.local", "db.internal", "10.0.0.7", "192.168.1.2", "[::1]"):
        assert internal_name(host), host
    for host in ("api.shop.test", "api-noauth.example.app", "47.246.1.1"):
        assert not internal_name(host), host
    assert all_private(["10.1.2.3", "fd00::1"]) and not all_private(["10.1.2.3", "47.246.1.1"])
    assert not all_private([])


def test_routes_written_relative_or_after_a_base() -> None:
    """Angular writes this.http.get("api/x"), relative to the site's root; others `${base}/api/x`."""
    js = (
        'this.http.get("api/product/get-bestsellers");this.http.post("api/product/get-availabilities",e);'
        'const u=`${this.base}/api/category/getRootCategories`;const m=`${e}/about`;const r="rapid/x";'
    )
    assert {r["route"]: r["method"] for r in routes_in(js)} == {
        "/api/product/get-bestsellers": "GET",
        "/api/product/get-availabilities": "POST",
        "/api/category/getRootCategories": "?",
    }


def test_where_the_nuxt_build_is() -> None:
    config = 'window.__NUXT__.config={app:{baseURL:"/",buildAssetsDir:"/static/b/",cdnURL:"https://cdn.shop.test"}}'
    assert builds_of(config) == ({"/static/b/"}, {"cdn.shop.test"})
    assert builds_of(NUXT_CONFIG) == ({"/_nuxt/"}, set()), "an empty cdnURL names none"
    assert builds_of('{"assetPrefix":"https://cdn.next.test","props":{}}') == (set(), {"cdn.next.test"})


def test_no_route_of_a_change_or_a_visitors_own_is_asked() -> None:
    """gme.cz's bundles: wish lists by GET and by no method shown, a store list, recommended products."""
    routes = [
        {"route": r, "method": m, "kind": route_kind(r)}
        for r, m in (
            ("/api/wish-lists/wish-lists-for-user", "GET"),
            ("/api/wish-lists/add-new", "?"),
            ("/api/store/get-list-hp", "GET"),
            ("/api/product/get-availabilities", "?"),
            ("/api/index/getRecommendedProducts", "GET"),
            ("/api/demand/temp/list", "?"),
        )
    ]
    assert [r["route"] for r in lists_to_ask(routes)] == ["/api/index/getRecommendedProducts", "/api/store/get-list-hp"]
    assert stateful("/addToCart") and stateful("/api/user/orders") and not stateful("/api/settings/social")


def test_a_helper_that_merges_its_parameters_in() -> None:
    """A helper written as an object's method that merges what it adds, as a minified bundle carries it, called
    before it is defined; a function that only names a sign, and a name holding the word inside a word of its
    own, are no helpers."""
    js = (
        'const n=t=>request({url:"/x",params:encrypt_default.addAntiSpiderParams(t)});'
        "encrypt_default={v_:v_,addAntiSpiderParams(e){const t=dayjs().valueOf().toString(),r=this.v_;"
        'let n="";if(!window.flag)return e;try{n=this.handleParams(t,e?.keyword)}catch(o){n="failure"}'
        "return e=Object.assign(e||{},{v:t,v_:r,p:n})}}"
    )
    assert helpers_in(js) == [{"name": "addAntiSpiderParams", "sets": ["v", "v_", "p"]}]
    assert helpers_in("const signParams=e=>{return{...e,sign:md5(e),ts}};") == [
        {"name": "signParams", "sets": ["sign", "ts"]}
    ]
    assert helpers_in("Ke={checkIsAddSign:function(e){e.properties.$is_first_day=!0}}") == [], "analytics"
    assert helpers_in("const assignParams=(t)=>{t.x=1};") == []


def test_which_base_is_the_apis_own() -> None:
    assert names_api(["apiHost", "API_HOST"]) and names_api(["baseURL"]) and names_api(["API_URL"])
    assert not names_api(["paymentApiUrl"]) and not names_api(["serverApiHost", "SERVER_API_HOST"])
    assert domain_of("www.shop.com") == domain_of("static-common.shop.com") == "shop.com"
    assert domain_of("a.shop.co.uk") == "shop.co.uk" and domain_of("10.1.2.3") == "10.1.2.3"
    assert same_domain("api.shop.test", "shop.test") and not same_domain("pay.vendor.test", "shop.test")
    assert not same_domain("", "shop.test")


def test_an_error_message_and_what_it_lacks() -> None:
    said = {"msg": "Either cate_id or keyword is required.", "total": 0}
    assert message_of(said) == "Either cate_id or keyword is required."
    assert message_of({"error": {"message": "Bad key"}}) == "Bad key" and message_of([1]) is None
    assert failed(message_of(said), 200) and failed("Not Found", 404)
    assert not failed("success", 200) and not failed(None, 500)
    assert wanted(message_of(said)) == ["cate_id", "keyword"]
    assert wanted("token is required") == [] and wanted("Invalid keyword") == []
    listings = ["https://shop.test/brands/acme/123450.html", "https://shop.test/category/eeprom/160112.html"]
    assert fill_for(["cate_id", "keyword"], "M24512-RMN6TP", listings) == {"keyword": "M24512-RMN6TP"}, "a fact first"
    assert fill_for(["cate_id", "keyword"], None, listings) == {"cate_id": "160112"}
    assert fill_for(["cate_id"], None, listings[:1]) is None, "a brand's number is no category's"
    assert fill_for(["cate_id"], "M24512", ["https://shop.test/category/?page=2"]) is None
