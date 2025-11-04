from Products.CMFCore.utils import getToolByName
from bs4 import BeautifulSoup
from plone.app.textfield.value import RichTextValue

from . import PloneSiteView

import re

from agsci.atlas.constants import DELIMITER, ACTIVE_REVIEW_STATES
from agsci.atlas.utilities import SitePeople, ploneify, getBodyHTML, isExternalStore, encode_blob
from agsci.atlas.content.pdf import AutoPDF
from agsci.atlas.content.article import IArticle
from agsci.atlas.content.video import IVideo
from agsci.atlas.content.event.group import IEventGroup
from agsci.atlas.content.event.webinar import IWebinar
from agsci.atlas.content.online_course.group import IOnlineCourseGroup
from agsci.atlas.content.behaviors import IAtlasAudience, IAtlasAudienceSkillLevel
from agsci.atlas.cron.jobs.magento import MagentoJob
from agsci.person.content.person import IPerson

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

        elif IEventGroup.providedBy(self.context) or IOnlineCourseGroup.providedBy(self.context):
            html = getBodyHTML(self.context)
            audience_html = []

            for iface in (IAtlasAudience, IAtlasAudienceSkillLevel):
                for (_name, _desc) in iface.namesAndDescriptions():
                    v = getattr(self.context.aq_base, _name, None)

                    if v:
                        if isinstance(v, RichTextValue):
                            v = v.output

                        if isinstance(v, str):
                            audience_html.append(
                                "<h2>%s</h2>%s" % (_desc.title, v)
                            )
                        elif isinstance(v, (list,tuple)):
                            items = ["<li>%s</li>" % x for x in v]
                            items_html = "<ul>%s</ul>" % " ".join(items)
                            audience_html.append(
                                "<h2>%s</h2>%s" % (_desc.title, items_html)
                            )

            return " ".join([x for x in (html, " ".join(audience_html)) if x])

        elif IPerson.providedBy(self.context):

            html = []

            bio = getattr(self.context.aq_base, 'bio', None)

            if bio:
                if isinstance(bio, str) and bio.strip():
                    html.append(bio)
                elif isinstance(bio, RichTextValue) and bio.output:
                    html.append(bio.output)

            areas_expertise = getattr(self.context.aq_base, 'areas_expertise', [])

            if areas_expertise:
                html.append('<h2>Expertise</h2>')
                items = ["<li>%s</li>" % x for x in areas_expertise]
                items_html = "<ul>%s</ul>" % " ".join(items)
                html.append(items_html)

            return " ".join(html)

        elif IWebinar.providedBy(self.context):

            # Start with group HTML
            html = [
                getBodyHTML(self.context.aq_parent),
            ]

            _ = self.webinar_recording_transcript

            if _:
                html.append("<h2>Transcript</h2>")
                html.append(_)

            return " ".join(html)

        return getBodyHTML(self.context)

    def getContent(self):

        description = self.context.Description()

        _rv = []

        if description:

            _rv.append(
                self.getContentStruct(
                    content_text = "<p>%s</p>" % description
                )
            )

        html = self.getHTML()

        if html:

            # Remove divs and spans
            html = re.sub(r'</*(div|span).*?>', '', html)

            # Remove attributes
            for _ in ['id', 'class', 'style', 'data-cvent-id']:
                html = re.sub(r' %s=".*?"' % _, '', html)

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

    api_merge_keys = [
        'product_type',
        'video_id',
        'language',
        'alternate_language',
        'continuing_education_credits',
        'credit_category_filter',
        'cvent_event_format',
    ]

    @property
    def modified(self):
        return self.context.modified().strftime('%Y-%m-%dT%H:%M:%S')

    @property
    def parent_extensionbot_view(self):
        return self.context.aq_parent.restrictedTraverse('@@extensionbot-psu')

    @property
    def parent_extensionbot_data(self):
        return self.parent_extensionbot_view.getData()

    @property
    def api_data(self):
        api_view = self.context.restrictedTraverse('@@api')
        return api_view.getData()

    @property
    def null_record(self):
        return self.hidden or self.product_not_visible or not self.active

    @property
    def additional_fields(self):
        return {}

    def getData(self, **kwargs):

        if self.null_record:
            return {
                'active' : False,
                'publication_id' : self.sku,
                'modified_date' : self.modified,
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
            'modified_date' : self.modified,
            'content_type' : 'HTML',
            'content' : self.getContent(),
            'category' : categories,
            'publication_id' : self.sku,
        }

        if _rv:

            if self.api_merge_keys:
                api_data = self.api_data

                for k in self.api_merge_keys:
                    if k in api_data and api_data[k]:
                        _rv[k] = api_data[k]

            _rv['active'] = self.active

            _rv.update(self.additional_fields)

            if 'share' in _rv:
                del _rv['share']

            return _rv

        return {}

class ExtensionBotPersonView(ExtensionBotPSUView):

    api_merge_keys = [
        'email_address',
        'person_job_title',
        'person_classification',
        'phone',
        'county',
    ]

    include_classifications = [
        'Faculty',
        'Educator',
        'Director',
        'Associate Director',
        'Assistant Director of Programs',
        'Assistant Director for County Operations',
        'Client Relationship Manager',
        'Business Operations Manager',
        'Leadership Team',
        'Staff',
    ]

    @property
    def hidden(self):
        # Only include educators and faculty
        classifications = getattr(self.context.aq_base, 'classifications', [])
        if classifications:
            if any([x in classifications for x in self.include_classifications]):
                return False
        return True

    def getCountyInfo(self, county):

        if county == 'University Park':

            # Hardcoded to Ag Admin
            return {
                'latitude' : '40.80249888',
                'longitude' : '-77.86382496',
            }

        elif county:

            results = self.portal_catalog.searchResults({
                'Type' : 'County',
                'Title' : county
            })

            for r in results:
                o = r.getObject()
                v = o.restrictedTraverse('@@api')
                _ = v.getData()

                return {
                    'latitude' : _.get('latitude', None),
                    'longitude' : _.get('longitude', None),
                }

        return {}

    @property
    def county_info(self):
        county = getattr(self.context.aq_base, 'county', [])

        if county:
            return self.getCountyInfo(county[0])

        return {}

    @property
    def additional_fields(self):

        _rv = {
            'product_type' : 'Person',
        }

        _rv.update(self.county_info)

        return _rv

class ExtensionBotPSUOnlineCourseGroupView(ExtensionBotPSUView):

    @property
    def additional_fields(self):

        _rv = {
            'product_type' : 'Online Course',
        }

        children = self.context.listFolderContents({'Type' : 'Online Course'})
        children = [x for x in children if self.wftool.getInfoFor(x, 'review_state') in ACTIVE_REVIEW_STATES]

        if children:
            children.sort(key=lambda x: x.effective())
            o = children[-1]
            v = o.restrictedTraverse('@@extensionbot-psu')
            if v.active:
                _ = getattr(o.aq_base, 'price', None)

                if _:
                    _rv['price'] = '%0.2f' % _

                _rv['author'] = v.getAuthors()

        return _rv

class ExtensionBotPSUCventEventView(ExtensionBotPSUView):

    api_merge_keys = [
        'price',
        'latitude',
        'longitude',
        'address',
        'city',
        'state',
        'zip',
        'event_start_date',
        'event_end_date',
        'registration_deadline',
        ]

    parent_merge_keys = [
        'language',
        'active',
        'content',
        'title',
        'continuing_education_credits',
        'credit_category_filter',
        'cvent_event_format',
    ]

    @property
    def additional_fields(self):
        _rv = {}

        product_type = getattr(self.context.aq_base, 'atlas_event_type', None)

        if product_type:
            _rv['product_type'] = product_type

        county = getattr(self.context.aq_base, 'county', None)

        if county and county and isinstance(county, (list, tuple)):
            _rv['county'] = county[0]

        if self.parent_merge_keys:
            parent_data = self.parent_extensionbot_data

            if parent_data and 'publication_id' in parent_data:
                _rv['parent_publication_id'] = parent_data['publication_id']

            for k in self.parent_merge_keys:
                if k in parent_data and parent_data[k]:
                    _rv[k] = parent_data[k]

        return _rv

    @property
    def modified(self):
        return sorted([self.context.modified(), self.context.aq_parent.modified()])[-1].strftime('%Y-%m-%dT%H:%M:%S')

    @property
    def entity_id(self):
        mj = MagentoJob(self.context)
        uid = self.context.UID()
        return mj.by_plone_id(uid).get('entity_id')

    def getPublicURL(self):
        magento_url = getattr(self.context.aq_parent, 'magento_url', None)

        if magento_url:
            entity_id = self.entity_id
            if entity_id:
                return 'https://extension.psu.edu/%s?entity=%s' % (magento_url, entity_id)
            return magento_url

    @property
    def null_record(self):
        if not super(ExtensionBotPSUCventEventView, self).null_record:
            return self.parent_extensionbot_view.null_record
        return True

class ExtensionBotPSUWebinarRecordingView(ExtensionBotPSUView):

    @property
    def webinar_recording_transcript(self):
        return self.api_data.get('transcript', None)

    @property
    def has_transcript(self):
        return not not self.webinar_recording_transcript

    @property
    def null_record(self):
        if self.parent_extensionbot_view.null_record:
            return True
        return not self.has_transcript

    def getPublicURL(self):
        return self.api_data.get('webinar_recorded_url', None)

class ExtensionBotPSUPodcastView(ExtensionBotPSUView):

    def getPublicURL(self):
        return self.api_data.get('video_url', None)

    # Temporarily using UID as SKU
    @property
    def sku(self):
        return self.context.UID()

class ExtensionBotPSUCountyView(ExtensionBotPSUView):

    api_merge_keys = [
        'email_address',
        'phone',
        'county',
        'address',
        'city',
        'state',
        'zip',
        'latitude',
        'longitude',
        'office_hours',
    ]

    @property
    def hidden(self):
        return False

class ExtensionBotPSUPublicationView(ExtensionBotPSUView):

    api_merge_keys = [
        'price',
        'language',
        'pages_count',
    ]

    @property
    def sku(self):

        api_data = self.api_data

        if 'contents' in api_data and api_data['contents']:
            for _ in api_data['contents']:
                if _.get('plone_product_type', None) in ('Publication Print',) \
                    and _.get('sku', None):
                        return _['sku']

        return super(ExtensionBotPSUPublicationView, self).sku

    @property
    def pdf(self):
        pdf_field = getattr(self.context.aq_base, 'pdf', None)

        if pdf_field:
            (pdf__mimetype, pdf_data) = encode_blob(pdf_field)

            if pdf__mimetype in ('application/pdf',):
                return pdf_data

    @property
    def isExternalStore(self):
        return isExternalStore(self.context.aq_base)

    @property
    def isEducationalPublication(self):
        publication_type = getattr(self.context.aq_base, 'internal_store_publication_type', None)
        if publication_type:
            return any([x in ('Educational Publications') for x in publication_type])

        return False


    # Is the product not expired/archived
    @property
    def active(self):
        if super(ExtensionBotPSUPublicationView, self).active:

            if not self.isExternalStore:
                return False

            if not self.isEducationalPublication:
                return False

            return True

        return False

    def get_normalized_sku(self, sku):
        results = self.portal_catalog.searchResults({
            'SKU' : sku,
            'review_state' : ACTIVE_REVIEW_STATES,
        })

        if not results:
            results = self.portal_catalog.searchResults({
                'SKU' : sku,
            })

        if results:
            o = results[0].getObject()
            v = o.restrictedTraverse('@@extensionbot-psu')
            return v.sku

    @property
    def alternate_language(self):
        rv = []

        api_data = self.api_data

        if 'alternate_language' in api_data and api_data['alternate_language']:
            for _ in api_data['alternate_language']:
                sku = _.get('sku', None)
                language = _.get('language', None)
                _sku = self.get_normalized_sku(sku)
                if _sku:
                    rv.append({'sku' : _sku, 'language' : language})

        return rv

    @property
    def additional_fields(self):

        return {
            'pdf' : self.pdf,
            'alternate_language' : self.alternate_language,
            'product_type' : 'Publication',
        }
