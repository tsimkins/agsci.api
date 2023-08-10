from .. import BaseView
from agsci.atlas.cron.jobs.magento import MagentoJob
from agsci.atlas.utilities import toISO
from DateTime import DateTime
from Products.CMFCore.utils import getToolByName

class PloneSiteView(BaseView):

    # Don't cache API views for the Plone site
    cache = False

    # Don't run 'expensive' adapters
    expensive = False

    # Listing of interfaces that products provide
    product_interfaces = [
                            'agsci.atlas.content.IAtlasProduct',
                            'agsci.atlas.content.behaviors.IAtlasInternalMetadata',
                            'agsci.atlas.content.behaviors.IAtlasProductCategoryMetadata',
                            'agsci.atlas.content.behaviors.IAtlasProductAttributeMetadata',
                            'agsci.atlas.content.behaviors.IAtlasEPASMetadata',
                            'agsci.atlas.content.ICounty',
                            'agsci.person.content.person.IPerson',
                        ]

    # Exclude these Types of objects from output.  Specifically, Person objects
    # will be handled separately (in the directory)
    exclude_types = ['Person', ]

    def products(self, sku=[], uid=[]):

        # Query for object having UID, if that parameter is provided
        if uid:

            return self.portal_catalog.searchResults({'UID' : uid})

        # Query for object having SKU, if that parameter is provided
        elif sku:

            results = self.portal_catalog.searchResults({
                'SKU' : sku,
                'object_provides' : 'agsci.atlas.content.IAtlasProduct',
            })

            if results:

                # Handle potential duplicate SKUs
                if len(results) > 1:
                    skus = [x.SKU for x in results if x.SKU]
                    mj = self.magento_data
                    uids = [mj.by_sku(x).get('plone_id') for x in skus]
                    results = [x for x in results if x.UID in uids]

                return results

    def getData(self, **kwargs):

        # Data structure to return
        data = {}

        # URL parameters
        uid = self.uids
        sku = self.skus

        modified = self.getModifiedCriteria()

        # Query for object having UID(s) or SKU(s), if those parameter are provided
        if uid or sku:

            results = self.products(uid=uid, sku=sku)

            if results:

                return {
                    'sku' : sku,
                    'plone_id' : uid,
                    'contents' : [x.getObject().restrictedTraverse('@@api').getData() for x in results]
                }

        # Otherwise, query for all products updated within X seconds, excluding
        # types configured above
        elif modified:

            # Initialize contents structure
            data["contents"] = []

            # Store 'modified' query string in response data
            data['modified'] = repr(modified)

            # Construct catalog query based on product types
            query = {
                        'object_provides' : self.product_interfaces,
                        'modified' : modified,
                        'effective' : {
                            'query' : DateTime(),
                            'range' : 'max',
                        },
                        'review_state' : ['published', 'expired', 'expiring_soon'],
                    }

            # Query catalog
            results = self.portal_catalog.searchResults(query)

            # Method to calculate sort order. For now, this puts the group
            # products first.
            def sortOrder(x):
                if x.Type.endswith(' Group'):
                    return 0
                return 1

            # Sort Results
            results = sorted(results, key=lambda x: sortOrder(x))

            # Iterate through results, skipping Person objects, and append
            # API export data to "contents" structure
            for r in results:

                # Exclude objects of a specified Type
                if r.Type in self.exclude_types:
                    continue

                o = r.getObject()

                # Traverse to the API view
                api_view = o.restrictedTraverse('@@api')

                # Append the data for this object
                data["contents"].append(api_view.data)

                # Extend contents with shadow products
                data["contents"].extend(api_view.getShadowData())

        return data

    def fmt_param(self, _):

        if isinstance(_, str):

            if ',' in _:
                return _.split(',')

        return _


    @property
    def uids(self):
        return self.fmt_param(self.request.get('UID', self.request.get('uid', self.request.get('plone_id', None))))

    @property
    def skus(self):
        return self.fmt_param(self.request.get('SKU', self.request.get('sku', None)))

    @property
    def magento_data(self):
        return MagentoJob(self.context)
