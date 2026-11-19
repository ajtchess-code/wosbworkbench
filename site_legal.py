"""Privacy policy, terms of use and copyright disclaimer for the public WoSB Wiki.

Plain-language pages written for a non-profit fan site that shows Google AdSense ads and runs behind Cloudflare.
They are a good-faith starting point, not legal advice; ``POLICY_DATE`` changes only when the wording changes.
"""
from __future__ import annotations

import html

POLICY_DATE = 'November 19, 2026'
GAME = 'World of Sea Battle'
OWNER = 'Thera Interactive'


def _e(s):
    return html.escape(str(s), quote=True)


def _contact(h):
    mail = h.get('contact_email') or ''
    parts = []
    if mail:
        parts.append(f'email <a href="mailto:{_e(mail)}">{_e(mail)}</a>')
    if h.get('discord_url'):
        parts.append(f'message the officers on the <a href="{_e(h["discord_url"])}" rel="noopener">Band of Misfits Discord</a>')
    return ' or '.join(parts) or 'contact the Band of Misfits officers through the guild Discord'


def privacy(h):
    site = h.get('site_name', 'WoSB Wiki'); url = h.get('site_url', '')
    return (
        f'<p class="note">Last updated: {POLICY_DATE}</p>'
        f'<p>This policy explains what information is collected when you visit the {_e(site)} at <a href="{_e(url)}">{_e(url)}</a>, who collects it, and the choices you have. '
        f'The {_e(site)} is a free, non-profit community fan site for {GAME}, run by volunteers from the Band of Misfits guild ("we").</p>'
        '<h2 id="summary">The short version</h2><ul>'
        '<li>The wiki has no accounts, sign-ups or forms. We never ask for your name, email or payment details.</li>'
        '<li>Our hosting and security provider, Cloudflare, processes your IP address and request details to deliver pages and stop attacks.</li>'
        '<li>Google AdSense shows ads and uses cookies. Where the law requires it, you are asked for consent first and can change your mind at any time.</li>'
        '<li>Interactive tools keep your settings in your own browser. We cannot see them.</li></ul>'
        '<h2 id="collect">Information we collect</h2>'
        '<p><b>Server and security data.</b> Like every website, each page request includes your IP address, browser type, the page asked for, the referring page and the time. '
        'Cloudflare, which hosts and protects the site, uses this to serve the page, keep it fast and block abusive traffic such as bots and scrapers. '
        'Cloudflare may set strictly necessary security cookies (for example <code>__cf_bm</code> or <code>cf_clearance</code>) to tell people from bots. '
        'We may see aggregate, anonymous statistics (page views, countries, errors). We do not use these to identify anyone.</p>'
        '<p><b>Data stored in your browser.</b> Tools such as the 3D ship viewer, damage simulator and battle simulator may save your choices (selected ship, designs, settings) '
        'in your browser\'s local storage so they are still there next time. This never leaves your device; clear your browser data to remove it.</p>'
        '<p><b>What we do not collect.</b> We do not run accounts, comments, newsletters or payment forms on this site, and we do not sell or rent personal information.</p>'
        '<h2 id="ads">Advertising and cookies</h2>'
        '<p>The site is paid for by donations and by ads served by Google AdSense. Google, as a third-party vendor, uses cookies to serve ads on this site. '
        'Google\'s advertising cookies let it and its partners serve ads based on your visits to this and other websites. '
        'You can opt out of personalised advertising at <a href="https://adssettings.google.com" rel="noopener">Google Ads Settings</a>, '
        'or opt out of some third-party vendors\' cookies at <a href="https://www.aboutads.info/choices/" rel="noopener">aboutads.info</a>. '
        'Read <a href="https://policies.google.com/technologies/partner-sites" rel="noopener">how Google uses information from sites that use its services</a>.</p>'
        '<p><b>Consent.</b> Visitors in the European Economic Area, the United Kingdom and Switzerland see a consent message, provided through Google\'s certified consent tool, '
        'before personalised ads or non-essential cookies are used. Visitors in US states with privacy laws (such as California) can opt out of the "sale" or "sharing" of '
        'personal information for targeted advertising through the same message or through Google Ads Settings. You can reopen your choices from the "Privacy and cookie settings" '
        'link where it is shown.</p>'
        '<h2 id="third">Other services we link to</h2>'
        '<p>Links to Discord, PayPal (donations), Steam and the official game site take you to services with their own privacy policies. '
        'Donations are handled entirely by PayPal; we never see your card details.</p>'
        '<h2 id="basis">Legal basis (EEA and UK visitors)</h2>'
        '<p>Security and server data is processed on the basis of our legitimate interest in running a safe, working website. Advertising cookies are used only with your consent '
        'where consent is required.</p>'
        '<h2 id="keep">How long data is kept</h2>'
        '<p>We do not store personal data ourselves. Cloudflare and Google keep data for the periods described in their own policies: '
        '<a href="https://www.cloudflare.com/privacypolicy/" rel="noopener">Cloudflare privacy policy</a>, '
        '<a href="https://policies.google.com/privacy" rel="noopener">Google privacy policy</a>.</p>'
        '<h2 id="rights">Your rights</h2>'
        '<p>Depending on where you live you may have the right to access, correct or delete personal data, to object to or restrict processing, and to withdraw consent. '
        'Because we do not keep personal data, most requests are best made to Google or Cloudflare directly, but we are happy to help: ' + _contact(h) + '.</p>'
        '<h2 id="children">Children</h2>'
        f'<p>The site is a general-audience reference for {GAME} and is not directed at children under 13. We do not knowingly collect personal information from children. '
        'If you believe a child has given us personal information, contact us and we will remove it.</p>'
        '<h2 id="changes">Changes</h2><p>If this policy changes we will update the date at the top of this page.</p>'
        '<h2 id="contact">Contact</h2><p>Questions about this policy: ' + _contact(h) + '.</p>')


def terms(h):
    site = h.get('site_name', 'WoSB Wiki')
    return (
        f'<p class="note">Last updated: {POLICY_DATE}</p>'
        f'<p>By using the {_e(site)} you agree to these terms. If you do not agree, please do not use the site.</p>'
        '<h2 id="what">What the site is</h2>'
        f'<p>The {_e(site)} is a free, unofficial, non-profit fan reference for {GAME}. Information is provided "as is", for personal and educational use. '
        'Game data is read from the public game client and can change with any game update; some values (for example damage rolls and fire chances) are decided by the game '
        'server and are estimates. We work to keep things accurate but make no guarantee that anything on the site is complete, current or error-free.</p>'
        '<h2 id="use">Acceptable use</h2><p>You may read, link to and share pages, and quote reasonable short extracts with a link back to the page. You may not:</p><ul>'
        '<li>copy, mirror, re-host or republish the site, its pages, data files, tools or 3D model packs, in whole or in substantial part;</li>'
        '<li>scrape, crawl or bulk-download the site with automated tools, other than search-engine indexing that follows our robots.txt;</li>'
        '<li>use the site\'s content or data to train machine-learning or AI models;</li>'
        '<li>frame the site inside another website, or present it as your own;</li>'
        '<li>extract the game assets shown in the viewers for reuse elsewhere;</li>'
        '<li>attack, overload, probe or try to bypass the site\'s security, or interfere with its ads.</li></ul>'
        '<h2 id="ip">Content ownership</h2>'
        f'<p>{GAME} and its names, logos, artwork, 3D models, textures, maps, text and other game content belong to {OWNER} and its licensors; see the '
        '<a href="disclaimer.html">copyright disclaimer</a>. The site\'s own writing, page design, tools, code, diagrams and the WoSB Wiki logo are © '
        f'{_e(site)} and Band of Misfits, all rights reserved, unless a page says otherwise.</p>'
        '<h2 id="links">Links</h2><p>Links to other websites are provided for convenience. We are not responsible for their content or practices.</p>'
        '<h2 id="ads">Ads and donations</h2><p>Ads are provided by Google AdSense. Donations are voluntary, made through PayPal, are not payment for any service and are not refundable '
        'through us.</p>'
        '<h2 id="liability">No warranty, limitation of liability</h2>'
        '<p>To the fullest extent the law allows, the site and everything on it is provided without warranties of any kind, and we are not liable for any loss or damage arising from '
        'its use, including in-game losses from decisions based on its data.</p>'
        '<h2 id="changes">Changes and access</h2><p>We may change these terms, or change, restrict or remove any part of the site, at any time. '
        'We may block access for anyone who breaks these terms.</p>'
        '<h2 id="contact">Contact</h2><p>' + _contact(h).capitalize() + '.</p>')


def disclaimer(h):
    site = h.get('site_name', 'WoSB Wiki')
    return (
        f'<p class="note"><b>{_e(site)} is an unofficial fan site.</b> It is not made, endorsed, sponsored or approved by {OWNER}, and is not affiliated with it in any way.</p>'
        '<h2 id="owner">Game content belongs to its owner</h2>'
        f'<p>{GAME}, its name and logo, and all game content shown or described on this site belong to {OWNER} and its licensors. That includes the ship and character '
        'imagery, icons, 3D models, textures, sails, flags and other designs, maps, sounds, in-game text and the game data the pages are built from. '
        f'All of these are trademarks or copyright of {OWNER}. They are used here for non-commercial reference and commentary, to help players '
        'understand the game, and no ownership of them is claimed.</p>'
        '<p>Ads on the site only cover hosting and running costs. The game content shown is not sold, licensed or offered for download.</p>'
        '<h2 id="ours">What is ours</h2>'
        f'<p>The written guides and explanations, page layouts, interactive tools and simulators, diagrams and the WoSB Wiki logo were made by the {_e(site)} and Band of Misfits '
        'contributors and are © their authors. See the <a href="terms.html">terms of use</a> for how they may be used.</p>'
        '<h2 id="accuracy">Accuracy</h2>'
        '<p>Values come from the game client and from player measurements, and can change with any game update. Nothing on this site is official game information.</p>'
        '<h2 id="takedown">Rights holders</h2>'
        f'<p>If you represent {OWNER} or another rights holder and want any material changed or removed, ' + _contact(h) +
        '. We will respond promptly and remove material on request.</p>')
