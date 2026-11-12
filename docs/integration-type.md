# Why `integration_type` is `service`

The manifest uses `"integration_type": "service"` and `"iot_class": "calculated"`.

- HA's manifest documentation describes `service` as "one service per config entry". Home Modes
  Advanced has exactly one config entry per household that provides one logical service (the
  house mode), which fits.
- `iot_class: calculated` is the documented class for integrations that talk to nothing and
  compute their result.
- `helper` is the documented type for integrations that "help users with automations" (the docs
  give derivative and group as examples) and would also fit. It would make the integration appear
  under Settings → Helpers. We kept `service` on purpose; revisit this if users expect to find it
  under Helpers.
