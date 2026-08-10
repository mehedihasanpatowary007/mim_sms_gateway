/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { Chatter } from "@mail/chatter/web_portal/chatter";
import { _t } from "@web/core/l10n/translation";
import { rpc } from "@web/core/network/rpc";

patch(Chatter.prototype, {
    /**
     * Handle Send SMS button click for both Contacts and CRM Leads
     */
    async onSendSMS() {
        // Check if we're on a contact or CRM lead form
        if (this.props.threadModel !== 'res.partner' && this.props.threadModel !== 'crm.lead') {
            this.env.services.notification.add(
                _t("This action is only available for contacts and leads"),
                { type: "warning" }
            );
            return;
        }

        // Validate threadId exists
        if (!this.props.threadId) {
            this.env.services.notification.add(
                _t("No record selected"),
                { type: "warning" }
            );
            return;
        }

        try {
            // Call the backend controller
            const result = await rpc("/chatter_custom/send_sms", {
                model: this.props.threadModel,
                res_id: this.props.threadId,
            });

            if (result.error) {
                // Show error notification if phone is missing or other error
                this.env.services.notification.add(
                    result.message || _t("Unable to send SMS"),
                    { type: "danger" }
                );
                return;
            }

            if (result.success && result.action) {
                // Open the SMS composer dialog
                await this.env.services.action.doAction(result.action);
            }
        } catch (error) {
            this.env.services.notification.add(
                _t("Error opening SMS composer. Please try again."),
                { type: "danger" }
            );
            console.error("Send SMS error:", error);
        }
    },
});