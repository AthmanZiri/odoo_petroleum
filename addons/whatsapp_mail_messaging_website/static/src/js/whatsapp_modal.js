/** @odoo-module **/
import publicWidget from "@web/legacy/js/public/public_widget";
import { rpc } from "@web/core/network/rpc";

publicWidget.registry.deliveryDateToggl = publicWidget.Widget.extend({
    selector: '#ModalWhatsapp',
    events: {
        'change .custom-default': 'onclickCustomRadio',
        'change .default-default': 'onclickDefaultRadio',
        'change #myFormControl': 'onSelectChange',
        'click .btn-danger': 'onCloseButtonClick',
        'click .btn-success': 'onSendMessageClick',
    },
    init() {
        this._super.apply(this, arguments);
    },
    onclickCustomRadio: function () {
        document.querySelector('#myFormControl').style.display = "none";
    },
    onclickDefaultRadio: function () {
        document.querySelector('#myFormControl').style.display = "block";
        let data = rpc('/whatsapp_message', {data:'data'});
        this.updateUI(data);
    },
    updateUI: function (data) {
        var selectElement = document.querySelector("#myFormControl");
        selectElement.innerHTML = '';
        var defaultOption = document.createElement('option');
        defaultOption.textContent = 'Select the Template';
        selectElement.appendChild(defaultOption);
        data.then((result) => {
            const messages = result.messages;
            messages.forEach((message) => {
                var option = document.createElement('option');
                option.value = message.id;
                option.textContent = message.name;
                option.setAttribute('data-message', message.message);
                selectElement.appendChild(option);
            });
        });
    },
    onSelectChange: function () {
        var selectElement = document.querySelector("#myFormControl");
        var textareaElement = document.querySelector("#exampleFormControlTextarea1");
        var selectedOption = selectElement.options[selectElement.selectedIndex];
        var selectedMessage = selectedOption.getAttribute('data-message');
        textareaElement.value = selectedMessage;
    },
    onCloseButtonClick: function () {
        document.querySelector("#ModalWhatsapp").style.display = "none";
    },
    onSendMessageClick: function () {
        var textareaElement = document.querySelector("#exampleFormControlTextarea1");
        var messageString = textareaElement.value;
        let data = rpc('/mobile_number', {data:'data'});
        data.then((result) => {
            const mobile_num = result.mobile;
            mobile_num.forEach(() => {
                if (mobile_num && mobile_num.length > 0 && 'mobile_number' in mobile_num[0] && mobile_num[0].mobile_number) {
                    var mobileNumber = mobile_num[0].mobile_number;
                    var whatsappUrl = 'https://api.whatsapp.com/send?phone=' + mobileNumber + '&text=' + encodeURIComponent(messageString);
                    window.open(whatsappUrl, '_blank');
                } else {
                    document.querySelector("#phoneMessage").style.display = "block";
                }
            });
        });
    },
});
export default publicWidget.registry.deliveryDateToggl;
