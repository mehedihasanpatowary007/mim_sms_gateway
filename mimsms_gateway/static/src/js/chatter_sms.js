/** @odoo-module **/

import { Chatter } from "@mail/chatter/web_portal/chatter";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { onWillStart, useState } from "@odoo/owl";

patch(Chatter.prototype, {
    setup() {
        super.setup(...arguments);
        this.actionService = useService("action");
        this.notificationService = useService("notification");
        this.smsGateway = useState({ available: false });
        this._mimsmsOpening = false;
        onWillStart(async () => {
            try {
                const result = await rpc("/mimsms_gateway/chatter/availability", {
                    model: this.props.threadModel,
                    res_id: this.props.threadId,
                });
                this.smsGateway.available = Boolean(result?.available);
            } catch {
                this.smsGateway.available = false;
            }
        });
    },

    async onMimsmsSendSms() {
        if (this._mimsmsOpening) {
            return;
        }
        this._mimsmsOpening = true;
        try {
            const result = await rpc("/mimsms_gateway/chatter/send", {
                model: this.props.threadModel,
                res_id: this.props.threadId,
            });
            if (result?.error) {
                this.notificationService.add(result.message || _t("Unable to open SMS composer"), {
                    type: "danger",
                });
                return;
            }
            if (result?.action) {
                await this.actionService.doAction(result.action);
            }
        } catch (error) {
            console.error("Could not open MiMSMS composer", error);
            const message = error?.data?.message || error?.message || _t("Unable to open the SMS composer");
            this.notificationService.add(message, {
                type: "danger",
            });
        } finally {
            this._mimsmsOpening = false;
        }
    },
});
