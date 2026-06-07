/** @odoo-module **/
import publicWidget from "@web/legacy/js/public/public_widget";

publicWidget.registry.WhatsappIcon = publicWidget.Widget.extend({
    selector: '.cy_whatsapp_web',
    events: {
        'click': '_onClickWhatsappIcon',
    },
    start: function() {
        this._super.apply(this, arguments);
    },
    _onClickWhatsappIcon: function () {
        $('#ModalWhatsapp').css('display', 'block');
    },
});
export default publicWidget.registry.WhatsappIcon;
