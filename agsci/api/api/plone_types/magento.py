from . import PloneSiteView
from agsci.atlas.cron.jobs.magento import MagentoJob
from agsci.atlas.utilities import ploneify

class InvalidMagentoURLKeysView(PloneSiteView):

    default_data_format = 'json'

    @property
    def magento_data(self):
        return MagentoJob(self.context)

    def get_product_url(self, product):

        product_type = product.get('product_type_value')
        title = product.get('name')

        suffix = {
            u'Publication Print' : 'print',
            u'Workshop Group' : 'workshop',
            u'Webinar Group' : 'webinar',
            u'Conference Group' : 'conference',
            u'Learn Now Video' : 'video',
            u'News Item' : 'news',
            u'Online Course Group' : 'online',
            u'Article' : None,
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
            _redirect = True

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
                _redirect = False

            # If we're an Article, but don't have any children, we can't redirect
            if r.Type in ['Article',] and not o.objectIds():
                _redirect = False

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

                    # Append product record with updated data to output
                    data.append(_)

                    # Do we have a Magento product with that URL already?
                    duplicate = magento_data.by_magento_url(set_magento_url)

                    # If we have an duplicate product, add some debug info
                    if duplicate:

                        # Copy the item so we can append to the output
                        _duplicate = dict(duplicate)

                        # Get the unique product url
                        _duplicate['set_url'] = self.get_product_url(_duplicate)

                        # Append the duplicate record if they're not the same
                        if _duplicate['set_url'] != _duplicate['magento_url']:
                            data.append(_duplicate)

        return data