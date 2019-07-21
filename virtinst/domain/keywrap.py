from ..xmlbuilder import XMLBuilder, XMLProperty, XMLChildProperty


class _KeyWrap(XMLBuilder):

    XML_NAME = "cipher"
    _XML_PROP_ORDER = ["name", "state"]

    name = XMLProperty("./@name")
    state = XMLProperty("./@state", is_onoff=True)


class DomainKeyWrap(XMLBuilder):
    """
    Class for generating <keywrap> XML
    """
    XML_NAME = "keywrap"

    cipher = XMLChildProperty(_KeyWrap)
