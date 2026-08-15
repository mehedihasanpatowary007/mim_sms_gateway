/** @odoo-module **/

import { Chatter } from "@mail/chatter/web_portal/chatter";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { onWillStart, useState } from "@odoo/owl";

patch(Chatter.prototype, {
    setup() {
        super.setup(...arguments);
        this.smsGateway = useState({ available: false, opening: false });
        onWillStart(async () => {
            const result = await rpc("/mimsms_gateway/chatter/availability", {
                model: this.props.threadModel,
                res_id: this.props.threadId,
            });
            this.smsGateway.available = Boolean(result?.available);
        });
    },

    async onMimsmsSendSms() {
        if (this.smsGateway.opening) {
            return;
        }
        this.smsGateway.opening = true;
        try {
            const result = await rpc("/mimsms_gateway/chatter/send", {
                model: this.props.threadModel,
                res_id: this.props.threadId,
            });
            if (result?.error) {
                this.env.services.notification.add(result.message || _t("Unable to open SMS composer"), {
                    type: "danger",
                });
                return;
            }
            if (result?.action) {
                await this.env.services.action.doAction(result.action);
            }
        } finally {
            this.smsGateway.opening = false;
        }
    },
});
