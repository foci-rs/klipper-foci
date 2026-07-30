
/// The paired order runs F,R,R,F,F,R,R,F so each direction takes both roles.
///
/// Under strict alternation a stroke's direction, whether it travels away from or
/// back to the origin, and the direction of the stroke before it are all locked
/// together. Pairing inverts the outbound/preceded-by relation relative to the
/// alternating orders, which is what separates them.
#[test]
fn paired_order_gives_each_direction_both_outbound_and_inbound_roles() {
    let order = IntegralSlotOrder::PairedOutAndBack;
    let expected = [0_usize, 1, 1, 0, 0, 1, 1, 0];
    for slot in 0..SLOT_COUNT {
        assert_eq!(
            order.direction_index(slot),
            expected[usize::from(slot)],
            "slot {slot}"
        );
    }

    // Even slots leave the origin, odd slots return to it, in every order.
    // Under the alternating orders an outbound stroke always follows an
    // opposite-direction stroke; under pairing it follows a same-direction one.
    for slot in (0..SLOT_COUNT).step_by(2) {
        let previous = if slot == 0 { SLOT_COUNT - 1 } else { slot - 1 };
        assert_eq!(
            order.direction_index(slot),
            order.direction_index(previous),
            "paired outbound slot {slot} must follow its own direction"
        );
        assert_ne!(
            IntegralSlotOrder::ForwardFirst.direction_index(slot),
            IntegralSlotOrder::ForwardFirst.direction_index(previous),
            "alternating outbound slot {slot} must follow the opposite direction"
        );
    }

    // Both excursion ends are used, so absolute position varies within a role.
    assert_eq!(order.direction_index(0), 0, "slot 0 leaves toward forward");
    assert_eq!(order.direction_index(2), 1, "slot 2 leaves toward reverse");
}
