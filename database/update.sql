-- 13. VIEWS

-- View: available_drivers
CREATE OR REPLACE VIEW available_drivers AS
SELECT driver_id, name, email, phone
FROM driver
WHERE availability_status = 'AVAILABLE';

-- View: active_rides
CREATE OR REPLACE VIEW active_rides AS
SELECT r.request_id, r.rider_id, r.status, a.driver_id, d.name AS driver_name
FROM ride_request r
JOIN assignment a ON r.request_id = a.request_id
JOIN driver d ON a.driver_id = d.driver_id
WHERE r.status IN ('ASSIGNED', 'IN_PROGRESS');

-- View: driver_ride_history
CREATE OR REPLACE VIEW driver_ride_history AS
SELECT d.driver_id, d.name, a.assignment_id, r.request_id, r.status, a.assigned_at
FROM driver d
JOIN assignment a ON d.driver_id = a.driver_id
JOIN ride_request r ON a.request_id = r.request_id;

-- View: completed_ride_summary
CREATE OR REPLACE VIEW completed_ride_summary AS
SELECT r.request_id, r.rider_id, a.driver_id, p.amount, p.processed_at
FROM ride_request r
JOIN assignment a ON r.request_id = a.request_id
JOIN payment p ON a.assignment_id = p.assignment_id
WHERE r.status = 'COMPLETED' AND p.status = 'COMPLETED';


-- 14. STORED PROCEDURES

-- Procedure: accept_ride
-- Encapsulates the transactional logic of accepting a ride.
CREATE OR REPLACE PROCEDURE accept_ride(request_id_in INT, driver_id_in INT)
LANGUAGE plpgsql
AS $$
DECLARE
    current_status VARCHAR;
BEGIN
    -- 1. Lock the ride request row to prevent concurrent modifications
    SELECT status INTO current_status 
    FROM ride_request 
    WHERE request_id = request_id_in 
    FOR UPDATE;

    -- 2. Check if the ride is still available
    IF current_status != 'SEARCHING' THEN
        RAISE EXCEPTION 'Ride is no longer available';
    END IF;

    -- 3. Update ride status
    UPDATE ride_request 
    SET status = 'ASSIGNED' 
    WHERE request_id = request_id_in;

    -- 4. Create assignment
    INSERT INTO assignment (request_id, driver_id) 
    VALUES (request_id_in, driver_id_in);

    -- 5. Update driver status to BUSY
    UPDATE driver 
    SET availability_status = 'BUSY' 
    WHERE driver_id = driver_id_in;

    -- 6. Update the offer status
    UPDATE ride_offer 
    SET status = 'ACCEPTED' 
    WHERE request_id = request_id_in AND driver_id = driver_id_in;
END;
$$;


-- 15. INDEXES for Optimization
CREATE INDEX IF NOT EXISTS idx_ride_status ON ride_request(status);
CREATE INDEX IF NOT EXISTS idx_driver_status ON driver(availability_status);
CREATE INDEX IF NOT EXISTS idx_ride_request_rider_id ON ride_request(rider_id);
