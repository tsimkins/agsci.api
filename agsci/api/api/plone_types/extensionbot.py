from Products.CMFCore.utils import getToolByName
from bs4 import BeautifulSoup

from . import PloneSiteView

from agsci.atlas.constants import DELIMITER, ACTIVE_REVIEW_STATES
from agsci.atlas.utilities import SitePeople, ploneify, getBodyHTML
from agsci.atlas.content.pdf import AutoPDF
from agsci.atlas.content.article import IArticle
from agsci.atlas.content.video import IVideo

class ExtensionBotView(PloneSiteView):

    default_data_format = 'json'

    @property
    def wftool(self):
        return getToolByName(self.context, 'portal_workflow')

    def getReviewState(self):
        return self.wftool.getInfoFor(self.context, 'review_state')

    @property
    def pdf_view(self):
        return AutoPDF(self.context)

    def getPersonInfo(self, _id):
        sp = SitePeople(active=False)
        r = sp.getPersonById(_id)
        if r:
            if r.review_state in (sp.active_review_state):
                o = r.getObject()
                email_address = getattr(o.aq_base, 'email_address', None)
                if email_address:
                    return "%s <%s>" % (r.Title, email_address)
            return r.Title

    def getAuthors(self):
        _ = getattr(self.context.aq_base, 'authors', [])

        if not _:
            return []

        _ = [self.getPersonInfo(x) for x in _]

        _ = [x for x in _ if x]

        return _

    def getPublicURL(self):
        _ = getattr(self.context.aq_base, 'magento_url', None)

        if _:
            return 'https://extension.psu.edu/%s' % _

    def getHTML(self):

        if IArticle.providedBy(self.context):
            return self.pdf_view.getArticleHTML()

        elif IVideo.providedBy(self.context):
            # Combine transcript with body html
            if hasattr(self.context, 'transcript') and \
               hasattr(self.context.transcript, 'output') and \
               self.context.transcript.output:
                    transcript = self.context.transcript.output
                    html = getBodyHTML(self.context)
                    return " ".join([x for x in (html, transcript) if x])

        return getBodyHTML(self.context)

    def getContent(self):

        description = self.context.Description()

        html = self.getHTML()

        if not html:
            return []

        soup = BeautifulSoup(html, features="lxml")

        # Fix links to other content on the site
        for a in soup.findAll('a'):
            href = a.get('href')
            url = self.pdf_view.getURLForUID(href)
            if url:
                a['href'] = url

        # Extract img tags
        for _ in soup.findAll(['iframe', 'embed','img']):
            _ = _.extract()

        _rv = []

        _ = self.getContentStruct(
            content_text = "<p>%s</p>" % description
        )

        for el in soup.body.findAll(recursive=False):
            # Skip blank

            if not el.text:
                continue

            if el.name in ['h%d' % x for x in range(1,7)]:
                _ = self.getContentStruct()
                _['content_header'] = str(el)
                _rv.append(_)

            else:

                if not _rv:
                    _rv.append(_)

                _rv[-1]['content_text'] = _rv[-1]['content_text'] + str(el)

        for _ in _rv:
            if 'content_text' not in _ or not _['content_text']:
                _['content_text'] = "<p></p>"

        return _rv

    def getContentStruct(self, **kwargs):
        _ = {
            'content_header' : '',
            'content_text' : '',
      #      'content_images' : [],
        }
        _.update(kwargs)
        return _

    def getL1Categories(self):
        _ = getattr(self.context.aq_base, 'atlas_category_level_1', [])
        if _:
            _ = [x.split(DELIMITER)[-1] for x in _]
            return sorted(set([x for x in _ if x]))
        return []

    def getL2Categories(self):
        _ = getattr(self.context.aq_base, 'atlas_category_level_2', [])
        if _:
            _ = [x.split(DELIMITER)[-1] for x in _]
            return sorted(set([x for x in _ if x]))
        return []

    # Does the data in the CMS match the data on the live site?
    @property
    def current(self):
        review_state = self.getReviewState()
        return review_state in ('published', 'expiring_soon')

    # Is the product not expired/archived
    @property
    def active(self):
        review_state = self.getReviewState()
        return review_state in ACTIVE_REVIEW_STATES

    @property
    def hidden(self):
        return getattr(self.context.aq_base, 'hide_product', False)

    @property
    def product_not_visible(self):
        return getattr(self.context.aq_base, 'hide_product', False)

    @property
    def sku(self):
        return getattr(self.context.aq_base, 'sku', None)

    # Get videos that are hidden, but in a series
    @property
    def video_series_skus(self):
        _rv = []

        results = self.portal_catalog.searchResults({
            'Type' : ['Learn Now Video Series'],
            'review_state' : ACTIVE_REVIEW_STATES,
        })

        for r in results:
            o = r.getObject()
            v = o.restrictedTraverse('@@extensionbot-psu')
            if v.include and v.current:
                _rv.extend([x.get('sku', None) for x in getattr(o.aq_base, 'videos') if x.get('sku', None)])

        return sorted(set(_rv))

    @property
    def include(self):

        hide_product = self.hidden
        product_not_visible = self.product_not_visible

        # Exclude hidden products except videos in series
        if hide_product or product_not_visible:
            if IVideo.providedBy(self.context):
                if self.sku not in self.video_series_skus:
                    return False
            else:
                return False

        # Exclude products without categories
        l1_categories = self.getL1Categories()
        l2_categories = self.getL2Categories()

        # Skip products without L2 categories
        if not self.getL2Categories():

            # ... unless Extension Products is in the L1
            if l1_categories and 'Extension Products' in l1_categories:
                pass
            else:
                return False

        # Exclude products without a URL
        if not self.getPublicURL():
            return False

        # Exclude with no SKU
        if not self.sku:
            return False

        return True

    def getData(self, **kwargs):

        if not self.include:
            return {}

        magento_url = self.getPublicURL()
        authors = self.getAuthors()
        categories = self.getL2Categories()

        _rv = {
            'title' : self.context.Title(),
            'state' : 'PA',
            'link' : magento_url,
            'share' : self.include,
            'institution' : 'Penn State Extension',
            'author' : authors,
            'publish_date' : self.context.effective().strftime('%Y-%m-%d'),
            'modified_date' : self.context.modified().strftime('%Y-%m-%dT%H:%M:%S'),
            'content_type' : 'HTML',
            'content' : self.getContent(),
            'category' : categories,
            'publication_id' : self.sku,
        }

        return _rv

class ExtensionBotPSUView(ExtensionBotView):


    def getData(self, **kwargs):

        if self.hidden or self.product_not_visible or not self.active:
            return {
                'active' : False,
                'publication_id' : self.sku,
                'modified_date' : self.context.modified().strftime('%Y-%m-%dT%H:%M:%S'),
            }


        magento_url = self.getPublicURL()
        authors = self.getAuthors()
        categories = self.getL2Categories()

        _rv = {
            'title' : self.context.Title(),
            'state' : 'PA',
            'link' : magento_url,
            'share' : self.include,
            'institution' : 'Penn State Extension',
            'author' : authors,
            'publish_date' : self.context.effective().strftime('%Y-%m-%d'),
            'modified_date' : self.context.modified().strftime('%Y-%m-%dT%H:%M:%S'),
            'content_type' : 'HTML',
            'content' : self.getContent(),
            'category' : categories,
            'publication_id' : self.sku,
        }

        if _rv:
            api_view = self.context.restrictedTraverse('@@api')
            api_data = api_view.getData()
            merge_keys = ['product_type', 'video_id', 'language', 'alternate_language']

            for k in merge_keys:
                if k in api_data and api_data[k]:
                    _rv[k] = api_data[k]

            _rv['active'] = self.active

            if 'share' in _rv:
                del _rv['share']

            return _rv

        return {}
