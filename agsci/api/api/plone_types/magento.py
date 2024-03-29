from DateTime import DateTime
from plone.app.uuid.utils import uuidToObject
from plone.memoize.instance import memoize

from . import PloneSiteView
from agsci.atlas.constants import EPAS_UNIT_LEADERS, \
    EPAS_TEAM_LEADERS, ACTIVE_REVIEW_STATES
from agsci.atlas.indexer import IsChildProduct
from agsci.atlas.utilities import SitePeople, ploneify

class MagentoView(PloneSiteView):

    default_data_format = 'json'

class ExpiringOwnerProducts(MagentoView):

    DEFAULT_DELTA = 62 # Days

    @property
    def delta(self):
        _ = self.request.get('delta', None)

        if _ and _.isdigit():
            return int(_)

        return self.DEFAULT_DELTA

    @property
    def agcomm_people(self):
        sp = SitePeople()
        _ = [x.getId for x in sp.agcomm_people]
        _.extend([u'sbj2',])
        return _

    @property
    @memoize
    def expiring_people(self):

        # Already expired people
        results = self.portal_catalog.searchResults({
            'Type' : 'Person',
            'review_state' : ['published-inactive', 'expired'],
        })

        agcomm_people = self.agcomm_people

        _ids = [x.getId for x in results if x.getId not in agcomm_people]

        # Expiring People

        results = self.portal_catalog.searchResults({
            'Type' : 'Person',
            'expires' : {
                'range' : 'max',
                'query' : DateTime() + self.delta, # Two Months
            }
        })

        _ids.extend([x.getId for x in results if x.getId not in agcomm_people])

        return list(set(_ids))

    def get_products_owned_by(self, _ids):

        return self.portal_catalog.searchResults({
            'object_provides' : 'agsci.atlas.content.IAtlasProduct',
            'Owners' : _ids,
            'review_state' : ACTIVE_REVIEW_STATES
        })

    def get_user_structure(self, r):

        now = DateTime()
        replace_owner = not not (now > r.expires or (r.expires - now) <= self.delta)

        return {
            'id' : r.getId,
            'name' : r.Title,
            'expires' : r.expires.strftime('%Y-%m-%d'),
            'replace_owner' : replace_owner,
            'plone_url' : r.getURL(),
        }

    def get_active_ids(self, o, field):

        # Get existing ids
        ids = getattr(o.aq_base, field, [])

        if not ids:
            return []

        # Copy of original ids, and remove   expiring ids
        return [x for x in ids if x and x not in self.expiring_people]

    def getData(self, **kwargs):

        _rv = []

        sp = SitePeople(active=False)
        agcomm_people = self.agcomm_people

        for r in self.get_products_owned_by(self.expiring_people):

            o = r.getObject()

            # Get the primary team
            epas_primary_team = getattr(o, 'epas_primary_team', None)

            # Original owners
            _owners = sorted(set((getattr(o.aq_base, 'owners', []))))

            # Get active owners and authors
            owners = self.get_active_ids(o, 'owners')
            authors = self.get_active_ids(o, 'authors')

            # Remove AgComm People
            owners = [x for x in owners if x not in agcomm_people]

            # If no active owners, use first author
            if not owners:
                if authors:
                    owners = [authors[0],]

            # Get new owners from EPAS team leader if no owners left.
            if not owners:

                # Get the team lead(s)

                owners = EPAS_TEAM_LEADERS.get(epas_primary_team, [])

                owners = [x for x in owners if x]

                # If no team leads assigned, go with the ADP
                if not owners:

                    if r.EPASUnit:

                        for _ in r.EPASUnit:
                            owners.extend(EPAS_UNIT_LEADERS.get(_, []))

            # Cleanup
            owners = [x for x in owners if x]
            owners = sorted(set(owners))

            # If our new owners don't match the original, add this to the rv
            if tuple(owners) != tuple(_owners):

                _rv.append({
                    'sku' : r.SKU,
                    'plone_product_type' : r.Type,
                    'plone_id' : r.UID,
                    'plone_url' : r.getURL(),
                    'name' : r.Title,
                    'primary_team' : epas_primary_team,
                    'unit' : ";".join(r.EPASUnit),
                    'team' : ";".join(r.EPASTeam),
                    'original_owners' : [self.get_user_structure(sp.getPersonById(x)) for x in _owners],
                    'new_owners' : [self.get_user_structure(sp.getPersonById(x)) for x in owners],
                })

        return _rv

class InvalidMagentoURLKeysView(MagentoView):

    def get_product_url(self, product):

        product_type = product.get('product_type_value')
        title = product.get('name')
        suffix = {
            "APPs" : "app",
            "Publication" : "print",
            "Smart Sheets" : "smartsheet",
            "Video Free" : "video",
            "Workshop Complex" : "workshop",
            "Workshop Simple" : "workshop",
        }.get(product_type, ploneify(product_type))

        url = ploneify(title)

        if suffix:
            return '%s-%s' % (url, suffix)

        return url

    def getData(self, **kwargs):

        # Get Magento data (from cron job)
        magento_data = self.magento_data

        # Data structure to return
        data = []

        # Get results of all Plone products in Magento with URL Check errors
        results = self.portal_catalog.searchResults({
            'UID' : magento_data.plone_ids,
            'ContentErrorCodes' : ['MagentoURLCheck',],
        })

        # Iterate through results
        for r in results:

            # Can we fix the URL with a redirect (this determines if it's a
            # product-level or product-grid fix)
            _edit_product = True

            # Skip people
            if r.Type in ['Person']:
                continue

            # Skip expired products
            if r.review_state in ['expired']:
                continue

            # Get the object
            o = r.getObject()

            # We can't redirect items without descriptions
            if not r.Description:
                _edit_product = False

            # If we're an Article, but don't have any children, we can't redirect
            if r.Type in ['Article',] and not o.objectIds():
                _edit_product = False

            # Get the Magento product data
            magento_product = magento_data.by_plone_id(r.UID)

            # Get Magento URL
            _magento_url = magento_product.get('magento_url', None)

            # If we have a Magento URL from Magento's data
            if _magento_url:

                # What the URLs should be
                set_magento_url = ploneify(r.Title)

                # If the Magento URL and the idea Magento URL are different..
                if _magento_url != set_magento_url:

                    # Value for product record
                    _ = dict(magento_product) # Copy
                    _['set_url'] = set_magento_url
                    _['plone_url'] = r.getURL().replace('http://', 'https://')

                    # Do we have a Magento product with that URL already?
                    duplicate = magento_data.by_magento_url(set_magento_url)

                    # If we have an duplicate product, add some debug info
                    if duplicate:

                        # Can't simply edit
                        _edit_product = False

                        # Copy the item so we can append to the output
                        _duplicate = dict(duplicate)

                        # Get the unique product url
                        _duplicate['set_url'] = self.get_product_url(_duplicate)

                        # Append the duplicate record if they're not the same
                        if _duplicate['set_url'] != _duplicate['magento_url']:
                            data.append(_duplicate)

                    # Set the value for editing the product
                    _['edit_product'] = _edit_product

                    # Append product record with updated data to output
                    data.append(_)

        return data

class OriginalPloneIdsView(MagentoView):

    types = [
        u'Webinar Group',
        u'Publication',
        u'Smart Sheet',
        u'App',
        u'Workshop Group',
        u'Conference Group',
        u'Learn Now Video',
        u'Article',
        u'News Item',
        u'Person'
    ]

    def getData(self, **kwargs):

        data = []

        results = self.portal_catalog.searchResults({
            'object_provides' : [
                'agsci.atlas.content.IAtlasProduct',
                'agsci.person.content.person.IPerson'
            ],
            'Type' : self.types
        })

        for r in results:

            if r.review_state in ['expired',]:
                continue

            plone_ids = r.OriginalPloneIds
            magento_url = r.MagentoURL

            if plone_ids and magento_url:

                for i in plone_ids:
                    data.append({'plone_id' : i, 'target' : '/%s' % magento_url})

        data.sort(key=lambda x: x.get('target'))
        return data

class ProductImageView(MagentoView):

    showBinary = False
    showSKU = False

    fields = [
        'plone_id',
        'sku',
        'magento_image_url',
    ]

    def get_magento_image_url(self, mj=None, uid=None):

        if uid:

            context = uuidToObject(uid)

            if context:

                if IsChildProduct(context)():
                    context = context.aq_parent

                _uid = context.UID()

                return mj.by_plone_id(_uid).get('thumbnail', None)

    def getData(self, **kwargs):

        mj = self.magento_data

        data = super(ProductImageView, self).getData(**kwargs)

        _contents = []

        if data:

            for _ in data.get('contents', []):
                _['magento_image_url'] = self.get_magento_image_url(mj, _.get('plone_id'))

                _contents.append(
                    dict([(x, _.get(x, None)) for x in self.fields])
                )

        data['contents'] = _contents

        return data
