-- Migration: move domains and projects nav items into the Inventory group
-- Previously they resided in customer_onboarding; users expect them under Inventory.
-- nav_items.key is globally unique, so we UPDATE the nav_group_id rather than inserting.

DO $$
DECLARE
    inventory_id INT;
BEGIN
    SELECT id INTO inventory_id FROM nav_groups WHERE key = 'inventory';
    IF inventory_id IS NOT NULL THEN
        UPDATE nav_items
           SET nav_group_id = inventory_id,
               sort_order   = 12
         WHERE key = 'domains';

        UPDATE nav_items
           SET nav_group_id = inventory_id,
               sort_order   = 13
         WHERE key = 'projects';
    END IF;
END $$;
