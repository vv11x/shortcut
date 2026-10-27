"""分类入口直接使用登记的静态图标；资源缺失时明确报错。"""
from .icon_theme import themed_icon


def category_pixmap(icon_key, size, light=True):
    image = themed_icon(icon_key, size)
    if image is None:
        raise KeyError('未登记的分类图标：' + str(icon_key))
    return image
