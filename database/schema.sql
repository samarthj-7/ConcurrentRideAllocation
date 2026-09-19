-- schema.sql
-- Database Schema for Concurrent Ride Allocation System

-- 1. RIDER Table
CREATE TABLE rider (
    rider_id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    phone VARCHAR(20) UNIQUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 2. DRIVER Table
CREATE TABLE driver (
    driver_id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    phone VARCHAR(20) UNIQUE NOT NULL,
    availability_status VARCHAR(20) NOT NULL CHECK (availability_status IN ('AVAILABLE', 'BUSY', 'OFFLINE')) DEFAULT 'OFFLINE',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 3. VEHICLE Table (1:N from DRIVER)
CREATE TABLE vehicle (
    vehicle_id SERIAL PRIMARY KEY,
    driver_id INTEGER NOT NULL REFERENCES driver(driver_id) ON DELETE CASCADE,
    make VARCHAR(50) NOT NULL,
    model VARCHAR(50) NOT NULL,
    license_plate VARCHAR(20) UNIQUE NOT NULL
);

-- 4. DRIVER_LOCATION Table (1:1 to DRIVER)
CREATE TABLE driver_location (
    location_id SERIAL PRIMARY KEY,
    driver_id INTEGER UNIQUE NOT NULL REFERENCES driver(driver_id) ON DELETE CASCADE,
    latitude DECIMAL(9,6) NOT NULL,
    longitude DECIMAL(9,6) NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 5. DRIVER_EARNINGS Table (1:N to DRIVER, or 1:1 if it's total)
-- The prompt specifies 1:N to DRIVER_EARNINGS for DRIVER. This means multiple earning records per driver (e.g. daily/weekly or just a ledger). I'll make it a ledger.
CREATE TABLE driver_earnings (
    earning_id SERIAL PRIMARY KEY,
    driver_id INTEGER NOT NULL REFERENCES driver(driver_id) ON DELETE CASCADE,
    amount DECIMAL(10,2) NOT NULL,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 6. RIDE_REQUEST Table (1:N from RIDER)
CREATE TABLE ride_request (
    request_id SERIAL PRIMARY KEY,
    rider_id INTEGER NOT NULL REFERENCES rider(rider_id) ON DELETE CASCADE,
    pickup_lat DECIMAL(9,6) NOT NULL,
    pickup_lon DECIMAL(9,6) NOT NULL,
    dropoff_lat DECIMAL(9,6) NOT NULL,
    dropoff_lon DECIMAL(9,6) NOT NULL,
    status VARCHAR(20) NOT NULL CHECK (status IN ('SEARCHING', 'ASSIGNED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED')) DEFAULT 'SEARCHING',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 7. RIDE_OFFER Table (1:N from RIDE_REQUEST, N:1 to DRIVER)
CREATE TABLE ride_offer (
    offer_id SERIAL PRIMARY KEY,
    request_id INTEGER NOT NULL REFERENCES ride_request(request_id) ON DELETE CASCADE,
    driver_id INTEGER NOT NULL REFERENCES driver(driver_id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL CHECK (status IN ('PENDING', 'ACCEPTED', 'REJECTED', 'EXPIRED')) DEFAULT 'PENDING',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(request_id, driver_id) -- A driver gets one offer per request
);

-- 8. CANCELLATION Table (1:0..1 to RIDE_REQUEST)
CREATE TABLE cancellation (
    cancellation_id SERIAL PRIMARY KEY,
    request_id INTEGER UNIQUE NOT NULL REFERENCES ride_request(request_id) ON DELETE CASCADE,
    reason TEXT,
    cancelled_by VARCHAR(20) NOT NULL CHECK (cancelled_by IN ('RIDER', 'DRIVER')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 9. ASSIGNMENT Table (1:0..1 from RIDE_REQUEST, N:1 to DRIVER)
CREATE TABLE assignment (
    assignment_id SERIAL PRIMARY KEY,
    request_id INTEGER UNIQUE NOT NULL REFERENCES ride_request(request_id) ON DELETE CASCADE,
    driver_id INTEGER NOT NULL REFERENCES driver(driver_id) ON DELETE CASCADE,
    assigned_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 10. PAYMENT Table (1:1 to ASSIGNMENT)
CREATE TABLE payment (
    payment_id SERIAL PRIMARY KEY,
    assignment_id INTEGER UNIQUE NOT NULL REFERENCES assignment(assignment_id) ON DELETE CASCADE,
    amount DECIMAL(10,2) NOT NULL,
    status VARCHAR(20) NOT NULL CHECK (status IN ('PENDING', 'COMPLETED', 'FAILED')) DEFAULT 'PENDING',
    processed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 11. RATING Table (1:0..1 to ASSIGNMENT)
CREATE TABLE rating (
    rating_id SERIAL PRIMARY KEY,
    assignment_id INTEGER UNIQUE NOT NULL REFERENCES assignment(assignment_id) ON DELETE CASCADE,
    score INTEGER NOT NULL CHECK (score >= 1 AND score <= 5),
    feedback TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 12. RIDE_STATUS_HISTORY Table (1:1 to ASSIGNMENT)
CREATE TABLE ride_status_history (
    history_id SERIAL PRIMARY KEY,
    assignment_id INTEGER UNIQUE NOT NULL REFERENCES assignment(assignment_id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL,
    changed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- TRIGGERS AND FUNCTIONS

-- Trigger function to add driver earnings when a payment is completed
CREATE OR REPLACE FUNCTION update_driver_earnings()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status = 'COMPLETED' AND (OLD.status IS NULL OR OLD.status != 'COMPLETED') THEN
        INSERT INTO driver_earnings (driver_id, amount, description)
        SELECT a.driver_id, NEW.amount, 'Payment for assignment ' || NEW.assignment_id
        FROM assignment a
        WHERE a.assignment_id = NEW.assignment_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_payment_completed
AFTER INSERT OR UPDATE ON payment
FOR EACH ROW
EXECUTE FUNCTION update_driver_earnings();

-- Trigger function to record status history when assignment is created
CREATE OR REPLACE FUNCTION record_assignment_history()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO ride_status_history (assignment_id, status)
    VALUES (NEW.assignment_id, 'ASSIGNED');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_assignment_created
AFTER INSERT ON assignment
FOR EACH ROW
EXECUTE FUNCTION record_assignment_history();

-- Trigger to update ride_status_history when ride_request status changes to IN_PROGRESS, COMPLETED, CANCELLED 
-- wait, the history is 1:1 to assignment. So we can't insert multiple records for the same assignment.
-- Let's update the existing record instead, as the prompt specifies a 1:1 relationship between ASSIGNMENT and RIDE_STATUS_HISTORY.
CREATE OR REPLACE FUNCTION update_assignment_history()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status IN ('IN_PROGRESS', 'COMPLETED', 'CANCELLED') THEN
        UPDATE ride_status_history
        SET status = NEW.status, changed_at = CURRENT_TIMESTAMP
        WHERE assignment_id = (SELECT assignment_id FROM assignment WHERE request_id = NEW.request_id);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_ride_request_status_changed
AFTER UPDATE OF status ON ride_request
FOR EACH ROW
WHEN (OLD.status IS DISTINCT FROM NEW.status)
EXECUTE FUNCTION update_assignment_history();
