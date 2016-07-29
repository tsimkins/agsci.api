from .. import BaseView
from agsci.common.utilities import encode_blob

class ImageView(BaseView):

    binary_data_fieldname = 'image'

    def getBinaryDataField(self):
        return getattr(self.context, self.binary_data_fieldname, None)

    def getData(self):
        data = super(ImageView, self).getData()

        data_field = self.getBinaryDataField()
        
        if data_field:
    
            (img_mimetype, img_data) = encode_blob(data_field, self.showBinaryData)
    
            if img_data:
                data['data'] = img_data
                data['mimetype'] = img_mimetype
        
        return data
