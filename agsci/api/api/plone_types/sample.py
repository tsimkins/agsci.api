from . import PloneSiteView
import itertools
from copy import copy

class SampleAPIView(PloneSiteView):

    placeholder = u'...'
    show_all_fields = True

    def updateValues(self, data, new_data):

        p = [dict, list, tuple, unicode, str, int, float, bool]

        def type_idx(i):
            try:
                return p.index(i.__class__)
            except ValueError:
                return 99999

        for k in new_data.keys():
            # If the current data item doesn't have an existing key, or an
            # empty/null key, replace the value with a copy of the new data.
            if not data.has_key(k) or \
               isinstance(data[k], None.__class__) or \
               not data[k] or \
               type_idx(new_data[k]) > type_idx(data[k]):
                data[k] = copy(new_data[k])

            # Otherwise, it's a valid value, combine them
            elif data.has_key(k):

                # If they're both dicts
                if isinstance(data[k], dict) and isinstance(new_data[k], dict):
                    data[k] = self.updateValues(data[k], new_data[k])

                # If they're both lists/tuples
                elif isinstance(data[k], (list, tuple)) and isinstance(new_data[k], (list, tuple)):
                    data[k] = list(data[k]) + list(new_data[k])

        return data

    def replaceValues(self, data):

        if isinstance(data, dict):
            for k in data.keys():
                data[k] = self.replaceValues(data[k])

        elif isinstance(data, (list, tuple)):
            data = [self.replaceValues(x) for x in data]

            # If data is entirely str/unicode, only present one item
            if all([isinstance(x, (str, unicode)) for x in data]):
                data = data[0:1]

            # If data is entirely list/tuple, combine contents into one list
            elif all([isinstance(x, (list, tuple)) for x in data]):
                data = [
                    self.replaceValues(list(itertools.chain(*data)))
                ]

            # If all children are dicts
            elif all([isinstance(x, dict) for x in data]):
                v = {}

                for i in data:
                    v.update(i)

                data = [v,]


        elif isinstance(data, (str, unicode)):
            data = self.placeholder

        elif isinstance(data, (int, float)):
            data = self.placeholder

        elif isinstance(data, None.__class__):
            data = self.placeholder

        return data

    def getData(self):

        # Data structure to return
        sample_data = {}

        # Construct catalog query based on product types
        query = {
                    'object_provides' : self.product_interfaces,
                }

        # Query catalog
        results = self.portal_catalog.searchResults(query)

        # Iterate through results, skipping Person objects, and append
        # API export data to "contents" structure
        for r in results:

            # Get object from brain
            o = r.getObject()

            # Traverse to the API view
            api_view = o.restrictedTraverse('@@api')

            # Update sample data with API output
            sample_data = self.updateValues(sample_data, api_view.getData())

            # Update sample data with shadow API output
            for i in api_view.getShadowData():
                sample_data.update(i)

        # Data structure to return
        data = {}

        # Replace strings with placeholders
        sample_data = self.replaceValues(sample_data)


        # Initialize contents structure
        data["contents"] = [sample_data,]

        # Store 'modified' query string in response data
        data['modified'] = self.placeholder

        return data
